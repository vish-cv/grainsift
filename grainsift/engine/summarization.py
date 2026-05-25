"""Summarization engine — generates an AI executive summary for a completed run."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.engine.aggregation import compute_category_accuracy, compute_dashboard_stats
from grainsift.engine.prompt_store import get_prompt
from grainsift.exceptions import LLMError
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.models.database import RawFeedback, Run

logger = logging.getLogger(__name__)


class SummaryResult(BaseModel):
    summary: str = Field(description="3-paragraph executive summary of the feedback run")


async def generate_run_summary(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
) -> str:
    """Generate, persist, and return an AI executive summary for a run."""
    run = await session.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    stats = await compute_dashboard_stats(run_id, session)

    # Date range from feedback rows
    date_row = (
        await session.execute(
            select(
                func.min(RawFeedback.feedback_date),
                func.max(RawFeedback.feedback_date),
            ).where(RawFeedback.run_id == run_id)
        )
    ).one()
    min_date, max_date = date_row
    if min_date and max_date:
        date_range = f"{min_date.strftime('%b %d, %Y')} – {max_date.strftime('%b %d, %Y')}"
    else:
        date_range = run.started_at.strftime("%b %d, %Y")

    top_cats = sorted(stats.volume_by_category, key=lambda c: -c.count)[:5]
    volume_summary = "\n".join(
        f"- {c.category}: {c.count} items" for c in top_cats
    ) or "- No labeled items"

    total = stats.total_labeled or 1
    sentiment_counts: dict[str, int] = {}
    for sb in stats.sentiment_by_category:
        for s in ("positive", "negative", "neutral", "mixed"):
            sentiment_counts[s] = sentiment_counts.get(s, 0) + getattr(sb, s)

    def pct(s: str) -> int:
        return round(sentiment_counts.get(s, 0) / total * 100)

    urg_dist = {u.urgency: u.count for u in stats.urgency_distribution}
    urgency_summary = "\n".join(
        f"- {u}: {c} items" for u, c in sorted(urg_dist.items(), key=lambda x: -x[1])
    ) or "- No urgency data"

    acc = await compute_category_accuracy(run_id, session)
    accuracy_pct = round(sum(acc.values()) / len(acc) * 100) if acc else 100

    system_prompt = await get_prompt(session, "summary_system", run.project_id)
    user_template = await get_prompt(session, "summary_user", run.project_id)

    user_content = user_template.format_map({
        "filename": run.filename,
        "date_range": date_range,
        "total": stats.total_labeled,
        "volume_summary": volume_summary,
        "pct_negative": pct("negative"),
        "pct_neutral": pct("neutral"),
        "pct_positive": pct("positive"),
        "urgency_summary": urgency_summary,
        "accuracy_pct": accuracy_pct,
    })

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        result = await llm.complete(messages, SummaryResult, max_tokens=1024)
    except Exception as exc:
        raise LLMError(f"Summary generation failed: {exc}") from exc

    run.ai_summary = result.summary
    run.completed_at = run.completed_at or datetime.now(UTC)
    await session.commit()

    return result.summary
