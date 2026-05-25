"""
Stage 3 — Discovery Engine.

Runs once before production extraction to help the user define their taxonomy.
Samples raw feedback, makes a single LLM call to suggest categories,
and persists the confirmed enum config.
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.config import Settings
from grainsift.engine.prompt_store import get_prompt
from grainsift.exceptions import EnumConfigError
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.models.database import EnumConfig, RawFeedback, Run
from grainsift.models.enums import EnumConfigSource, RunStatus
from grainsift.models.schemas import EnumCategory


# ─── Public response models ───────────────────────────────────────────────────


class TaxonomySource(BaseModel):
    """A previous run's taxonomy, available for import."""
    run_id: str
    filename: str
    category_count: int
    categories: list[EnumCategory]

logger = logging.getLogger(__name__)

_MIN_CATEGORIES = 5
_MAX_CATEGORIES = 15
_OTHER_CATEGORY = EnumCategory(
    key="other",
    label="Other",
    description="Feedback that does not fit any of the defined categories.",
    examples=[],
)

# ─── LLM response models ──────────────────────────────────────────────────────


class _SuggestedCategory(BaseModel):
    key: str
    label: str
    description: str = ""
    examples: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, v: object) -> str:
        import re

        v = str(v).lower().strip()
        v = re.sub(r"[^a-z0-9]+", "_", v).strip("_")
        return v or "unknown"


class _DiscoveryResponse(BaseModel):
    categories: list[_SuggestedCategory] = Field(min_length=1, max_length=20)


# ─── Public interface ─────────────────────────────────────────────────────────


async def run_discovery(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    settings: Settings,
    sample_size: int = 250,
    locked_categories: list[EnumCategory] | None = None,
) -> list[EnumCategory]:
    """
    Sample up to `sample_size` rows from the run's raw_feedback,
    call the LLM once, and return suggested categories.
    If `locked_categories` is provided, those categories are preserved in the
    output and the LLM is asked only to fill in gaps around them.
    Does NOT persist anything — call save_enum_config separately after
    the user confirms/edits the suggestions.
    """
    run = await session.get(Run, run_id)
    if not run:
        raise EnumConfigError(f"Run {run_id} not found")

    # ── Sample feedback rows ──────────────────────────────────────────────────
    total: int = (
        await session.scalar(
            select(func.count()).where(RawFeedback.run_id == run_id)
        )
    ) or 0

    if total == 0:
        raise EnumConfigError(
            f"Run {run_id} has no ingested feedback. Run ingest first."
        )

    rows = (
        await session.execute(
            select(RawFeedback.clean_text)
            .where(RawFeedback.run_id == run_id, RawFeedback.clean_text.is_not(None))
            .order_by(func.random())
            .limit(sample_size)
        )
    ).scalars().all()

    if not rows:
        raise EnumConfigError("No clean feedback text available for discovery.")

    logger.info(
        "Discovery for run %s: sampling %d / %d rows", run_id, len(rows), total
    )

    # ── Build prompt and call LLM ─────────────────────────────────────────────
    feedback_json = json.dumps(
        [{"index": i, "text": t} for i, t in enumerate(rows)], ensure_ascii=False
    )

    locked_section = ""
    locked_keys: set[str] = set()
    if locked_categories:
        pinned = [c for c in locked_categories if c.key != "other"]
        if pinned:
            locked_keys = {c.key for c in pinned}
            pinned_json = json.dumps(
                [{"key": c.key, "label": c.label, "description": c.description} for c in pinned],
                ensure_ascii=False,
            )
            locked_section = (
                "\nThe following categories are LOCKED and MUST appear in your output unchanged. "
                "Do not modify, merge, or remove them. You may add new categories beyond these:\n"
                + pinned_json
            )

    system_prompt = await get_prompt(session, "discovery_system", run.project_id)
    user_template = await get_prompt(session, "discovery_user", run.project_id)
    user_content = user_template.format_map({
        "n": len(rows),
        "min_categories": _MIN_CATEGORIES,
        "max_categories": _MAX_CATEGORIES,
        "feedback_json": feedback_json,
        "locked_section": locked_section,
    })

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response: _DiscoveryResponse = await llm.complete(
        messages=messages,
        response_model=_DiscoveryResponse,
        max_retries=2,
    )

    # ── Convert to public schema, merging locked categories first ─────────────
    suggested: list[EnumCategory] = []
    seen_keys: set[str] = set(locked_keys)

    # Always include locked categories first, exactly as supplied
    if locked_categories:
        for cat in locked_categories:
            if cat.key != "other":
                suggested.append(cat)

    # Add new categories from LLM that don't overlap with locked ones
    for raw in response.categories:
        if raw.key in seen_keys or raw.key == "other":
            continue
        seen_keys.add(raw.key)
        suggested.append(
            EnumCategory(
                key=raw.key,
                label=raw.label,
                description=raw.description,
                examples=raw.examples[:3],
            )
        )

    logger.info("Discovery returned %d categories for run %s", len(suggested), run_id)
    return suggested


async def save_enum_config(
    run_id: str,
    categories: list[EnumCategory],
    session: AsyncSession,
    created_by: EnumConfigSource = EnumConfigSource.DISCOVERY,
) -> EnumConfig:
    """
    Persist the user-confirmed category list to the DB.
    Automatically appends the 'other' category if not already present.
    Returns the new EnumConfig row.
    """
    if not categories:
        raise EnumConfigError("Cannot save an empty category list.")

    # Ensure 'other' is always last
    keys = [c.key for c in categories]
    if "other" not in keys:
        categories = list(categories) + [_OTHER_CATEGORY]

    # Determine next version number for this run
    latest_version: int = (
        await session.scalar(
            select(func.max(EnumConfig.version)).where(EnumConfig.run_id == run_id)
        )
    ) or 0

    config = EnumConfig(
        run_id=run_id,
        version=latest_version + 1,
        categories=_categories_to_dict(categories),
        created_by=created_by,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)

    logger.info(
        "Saved enum config v%d for run %s: %d categories",
        config.version,
        run_id,
        len(categories),
    )
    return config


async def get_latest_enum_config(
    run_id: str, session: AsyncSession
) -> EnumConfig | None:
    """Return the most recent confirmed enum config for a run, or None."""
    return (
        await session.scalar(
            select(EnumConfig)
            .where(EnumConfig.run_id == run_id)
            .order_by(EnumConfig.version.desc())
            .limit(1)
        )
    )


def enum_config_to_categories(config: EnumConfig) -> list[EnumCategory]:
    """Deserialize categories JSON back into EnumCategory objects."""
    raw: list[dict[str, Any]] = config.categories.get("categories", [])
    return [EnumCategory(**item) for item in raw]


def get_allowed_keys(config: EnumConfig) -> list[str]:
    """Return just the category keys from a saved enum config."""
    return [c.key for c in enum_config_to_categories(config)]


async def list_runs_with_taxonomy(
    run_id: str,
    session: AsyncSession,
) -> list[TaxonomySource]:
    """
    Return other runs that have a saved taxonomy, newest first.
    Used to populate the "import from previous run" picker.
    """
    all_rows = (
        await session.execute(
            select(
                Run.id.label("run_id"),
                Run.filename,
                Run.started_at,
                EnumConfig.version,
                EnumConfig.categories,
            )
            .join(EnumConfig, EnumConfig.run_id == Run.id)
            .where(Run.id != run_id)
            .order_by(Run.started_at.desc(), EnumConfig.version.desc())
        )
    ).all()

    seen: set[str] = set()
    sources: list[TaxonomySource] = []
    for row in all_rows:
        if row.run_id in seen:
            continue
        seen.add(row.run_id)
        raw_cats: list[dict[str, Any]] = row.categories.get("categories", []) if row.categories else []
        categories = [
            EnumCategory(**c)
            for c in raw_cats
            if c.get("key") != "other"
        ]
        sources.append(
            TaxonomySource(
                run_id=row.run_id,
                filename=row.filename,
                category_count=len(categories),
                categories=categories,
            )
        )
    return sources


async def import_taxonomy_from_run(
    run_id: str,
    source_run_id: str,
    session: AsyncSession,
) -> list[EnumCategory]:
    """
    Return the categories from another run's latest taxonomy (without persisting).
    The caller is responsible for showing the edit screen and calling save_enum_config.
    """
    source_config = await get_latest_enum_config(source_run_id, session)
    if source_config is None:
        raise EnumConfigError(f"No taxonomy found for run {source_run_id}")
    cats = enum_config_to_categories(source_config)
    return [c for c in cats if c.key != "other"]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _categories_to_dict(categories: list[EnumCategory]) -> dict[str, Any]:
    return {"categories": [c.model_dump() for c in categories]}
