"""
End-to-end smoke test: ingest → discovery → extraction → dashboard.
Runs the full v0.1 pipeline against the sample CSV using the real LLM
configured in .env. Makes exactly ~6 LLM calls on a 25-row dataset.

Usage (from repo root):
    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── make sure we can import grainsift from repo root ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grainsift.config import get_settings
from grainsift.engine.aggregation import compute_dashboard_stats
from grainsift.engine.discovery import run_discovery, save_enum_config
from grainsift.engine.extraction import estimate_extraction_cost, run_extraction
from grainsift.engine.ingest import ingest_csv
from grainsift.llm.client import create_llm_client
from grainsift.models.database import Base, Run, configure_sqlite_pragmas
from grainsift.models.enums import RunStatus
from grainsift.models.schemas import ColumnMapping

console = Console()
SAMPLE_CSV = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_feedback.csv"


async def main() -> None:
    settings = get_settings()

    console.print(Panel(
        f"[bold green]GrainSift Smoke Test[/bold green]\n\n"
        f"Provider : {settings.llm_provider}\n"
        f"Model    : {settings.active_model}\n"
        f"CSV      : {SAMPLE_CSV.name} ({SAMPLE_CSV.stat().st_size} bytes)\n"
        f"Batch sz : {settings.batch_size}",
        border_style="green",
    ))

    # ── 1. Setup in-memory DB ─────────────────────────────────────────────────
    console.print("\n[bold]Step 1/5[/bold] Setting up database…")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    configure_sqlite_pragmas(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── 2. Ingest ─────────────────────────────────────────────────────────────
    console.print("[bold]Step 2/5[/bold] Ingesting sample CSV…")
    async with session_factory() as session:
        run = Run(filename=SAMPLE_CSV.name, status=RunStatus.PENDING)
        session.add(run)
        await session.commit()
        await session.refresh(run)

        content = SAMPLE_CSV.read_bytes()
        mapping = ColumnMapping(
            feedback_column="feedback",
            date_column="date",
            source_column="source",
        )
        ingest_result = await ingest_csv(
            run_id=run.id,
            content=content,
            column_mapping=mapping,
            session=session,
            settings=settings,
        )

    _print_ingest(ingest_result)

    if ingest_result.accepted_rows == 0:
        console.print("[red]No rows accepted. Aborting.[/red]")
        return

    # ── 3. Discovery (1 LLM call) ─────────────────────────────────────────────
    console.print("\n[bold]Step 3/5[/bold] Running discovery… [dim](1 LLM call)[/dim]")
    llm = create_llm_client(settings)

    async with session_factory() as session:
        suggested = await run_discovery(
            run_id=run.id,
            session=session,
            llm=llm,
            settings=settings,
            sample_size=50,  # use all rows for small dataset
        )

    _print_categories(suggested)

    # Auto-confirm all suggestions (smoke test — no human editing)
    async with session_factory() as session:
        enum_config = await save_enum_config(
            run_id=run.id,
            categories=suggested,
            session=session,
        )
    console.print(f"  [green]✓[/green] Enum config v{enum_config.version} saved — "
                  f"{len(suggested) + 1} categories (including 'other')")

    # ── 4. Cost estimate before extraction ───────────────────────────────────
    console.print("\n[bold]Step 4/5[/bold] Estimating extraction cost…")
    async with session_factory() as session:
        estimate = await estimate_extraction_cost(
            run_id=run.id,
            session=session,
            llm=llm,
            settings=settings,
        )
    console.print(
        f"  Items     : {estimate.estimated_items}\n"
        f"  API calls : {estimate.estimated_api_calls}\n"
        f"  Est. cost : ${estimate.estimated_cost_usd:.4f} USD\n"
        f"  Est. time : ~{estimate.estimated_minutes} min"
    )

    # ── 5. Extraction (~5 LLM calls) ─────────────────────────────────────────
    console.print(f"\n[bold]Step 5/5[/bold] Running extraction… "
                  f"[dim](~{estimate.estimated_api_calls} LLM calls)[/dim]")
    async with session_factory() as session:
        extraction_result = await run_extraction(
            run_id=run.id,
            session=session,
            llm=llm,
            settings=settings,
        )

    _print_extraction(extraction_result)

    # ── Dashboard stats ───────────────────────────────────────────────────────
    console.print("\n[bold cyan]Dashboard Stats[/bold cyan]")
    async with session_factory() as session:
        stats = await compute_dashboard_stats(run.id, session)

    _print_dashboard(stats)

    # ── Summary ───────────────────────────────────────────────────────────────
    actual_cost = extraction_result.actual_cost_usd
    console.print(Panel(
        f"[bold green]Smoke test complete[/bold green]\n\n"
        f"Total LLM calls  : ~{1 + estimate.estimated_api_calls}\n"
        f"Items processed  : {extraction_result.processed_items}\n"
        f"Items for review : {extraction_result.flagged_items}\n"
        f"Actual cost      : ${actual_cost:.4f} USD",
        border_style="green",
    ))

    await engine.dispose()


# ── Pretty printers ───────────────────────────────────────────────────────────

def _print_ingest(r) -> None:
    console.print(
        f"  Total rows   : {r.total_rows}\n"
        f"  Accepted     : [green]{r.accepted_rows}[/green]\n"
        f"  Duplicates   : {r.duplicate_rows}\n"
        f"  Skipped      : {r.skipped_rows}\n"
        f"  PII redacted : {r.pii_redactions}\n"
        f"  Languages    : {r.language_distribution}"
    )


def _print_categories(cats) -> None:
    t = Table("Key", "Label", "Description", box=None, padding=(0, 2))
    for c in cats:
        t.add_row(c.key, c.label, c.description[:60] + ("…" if len(c.description) > 60 else ""))
    console.print(t)


def _print_extraction(r) -> None:
    console.print(
        f"  Processed    : [green]{r.processed_items}[/green]\n"
        f"  For review   : [yellow]{r.flagged_items}[/yellow]\n"
        f"  Errors       : [red]{r.error_items}[/red]\n"
        f"  Actual cost  : ${r.actual_cost_usd:.4f} USD"
    )


def _print_dashboard(stats) -> None:
    t = Table("Category", "Count", "% of total", box=None, padding=(0, 2))
    total = stats.total_labeled or 1
    for c in stats.volume_by_category:
        pct = f"{c.count / total * 100:.0f}%"
        t.add_row(c.category, str(c.count), pct)
    console.print(t)

    sentiment_line = (
        f"Sentiment: "
        + " | ".join(
            f"{s.category}→[green]+{s.positive}[/green]/[red]-{s.negative}[/red]"
            for s in stats.sentiment_by_category[:4]
        )
    )
    console.print(sentiment_line)
    console.print(f"'other' volume: {stats.other_volume} ({stats.other_pct}%)")


if __name__ == "__main__":
    asyncio.run(main())
