"""
Stage 4 — Extraction Engine.

Classifies every raw_feedback item against the user's confirmed enum list.
Batches 5 items per LLM call. Uses a dynamically-built Pydantic model so
instructor enforces the category enum on every response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.config import Settings
from grainsift.engine.discovery import get_allowed_keys, get_latest_enum_config
from grainsift.engine.prompt_store import get_prompt
from grainsift.engine.validation import get_review_flags, is_random_sample, needs_human_review
from grainsift.exceptions import EnumConfigError, LLMError, LLMValidationError
from grainsift.llm.prompts import EXTRACTION
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.models.database import EnumConfig, Label, RawFeedback, Run
from grainsift.models.enums import FeedbackStatus, LabelSource, RunStatus, Sentiment, Urgency
from grainsift.models.schemas import CostEstimate

logger = logging.getLogger(__name__)

# ─── Token / cost estimation constants ───────────────────────────────────────

_AVG_FEEDBACK_TOKENS = 120     # average tokens per feedback item
_PROMPT_OVERHEAD_TOKENS = 600  # system prompt + categories list per batch call
_AVG_OUTPUT_TOKENS = 60        # tokens per labeled item in response


# ─── Dynamic model factory ────────────────────────────────────────────────────


def _build_batch_model(allowed_categories: list[str]) -> type[BaseModel]:
    """
    Build a Pydantic model whose `category` field is constrained to the
    user's confirmed category list. Instructor will auto-retry on violations.
    """
    CategoryEnum = StrEnum("CategoryEnum", {c: c for c in allowed_categories})

    class _SingleLabel(BaseModel):
        item_index: int = Field(ge=0)
        category: CategoryEnum  # type: ignore[valid-type]
        sentiment: Sentiment
        urgency: Urgency
        key_phrase: str | None = Field(default=None, max_length=120)
        confidence: float = Field(ge=0.0, le=1.0)

    class _BatchResult(BaseModel):
        labels: list[_SingleLabel]

    return _BatchResult


# ─── Result types ─────────────────────────────────────────────────────────────


@dataclass
class ExtractionProgress:
    total_items: int
    processed: int = 0
    flagged: int = 0
    errors: int = 0
    actual_cost_usd: float = 0.0

    @property
    def pct_complete(self) -> float:
        return round(self.processed / self.total_items * 100, 1) if self.total_items else 0.0


@dataclass
class ExtractionResult:
    run_id: str
    total_items: int
    processed_items: int
    flagged_items: int
    error_items: int
    actual_cost_usd: float
    enum_config_version: int
    low_confidence_categories: list[str] = field(default_factory=list)


@dataclass
class _ProcessingUnit:
    """One logical feedback item to label — may represent multiple DB chunks."""
    text: str                        # merged text sent to LLM
    primary: RawFeedback             # chunk_index == 0 (gets the label)
    siblings: list[RawFeedback]      # chunk_index > 0 (marked PROCESSED, no label)


def _build_processing_units(pending: list[RawFeedback]) -> list[_ProcessingUnit]:
    """
    Group multi-chunk rows (same content_hash, total_chunks > 1) into one
    ProcessingUnit each. Single-chunk rows each become their own unit.
    The merged text is all chunks concatenated in chunk_index order.
    """
    groups: dict[str, list[RawFeedback]] = defaultdict(list)
    for item in pending:
        if item.total_chunks > 1:
            groups[item.content_hash].append(item)
        else:
            # Yield directly as a single unit
            groups[f"__single__{item.id}"].append(item)

    units: list[_ProcessingUnit] = []
    for items in groups.values():
        if len(items) == 1:
            it = items[0]
            units.append(_ProcessingUnit(
                text=it.clean_text or it.original_text,
                primary=it,
                siblings=[],
            ))
        else:
            # Sort by chunk_index; chunk 0 is primary
            sorted_items = sorted(items, key=lambda x: x.chunk_index)
            primary = sorted_items[0]
            siblings = sorted_items[1:]
            merged_text = " ".join(
                (it.clean_text or it.original_text) for it in sorted_items
            )
            units.append(_ProcessingUnit(
                text=merged_text,
                primary=primary,
                siblings=siblings,
            ))
    return units


# ─── Cost estimation ──────────────────────────────────────────────────────────


async def estimate_extraction_cost(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    settings: Settings,
) -> CostEstimate:
    """
    Return a cost/time estimate without running extraction.
    Called by the UI before the user confirms the run.
    """
    total_items: int = (
        await session.scalar(
            select(RawFeedback.id).where(
                RawFeedback.run_id == run_id,
                RawFeedback.status == FeedbackStatus.PENDING,
            ).correlate_except(RawFeedback)
        )
    ) or 0

    # count pending items properly
    from sqlalchemy import func
    total_items = (
        await session.scalar(
            select(func.count()).where(
                RawFeedback.run_id == run_id,
                RawFeedback.status == FeedbackStatus.PENDING,
            )
        )
    ) or 0

    api_calls = math.ceil(total_items / settings.batch_size)
    input_tokens = api_calls * (_PROMPT_OVERHEAD_TOKENS + settings.batch_size * _AVG_FEEDBACK_TOKENS)
    output_tokens = total_items * _AVG_OUTPUT_TOKENS
    cost = llm.estimate_cost(input_tokens, output_tokens)

    # rough estimate: ~2s per API call, most parallelised
    estimated_minutes = round(api_calls * 2 / 60, 1)

    return CostEstimate(
        provider=llm.provider_name,
        model=llm.model_name,
        estimated_items=total_items,
        estimated_api_calls=api_calls,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_usd=round(cost, 4),
        estimated_minutes=estimated_minutes,
    )


# ─── Main extraction function ─────────────────────────────────────────────────


async def run_extraction(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    settings: Settings,
    enum_config: EnumConfig | None = None,
) -> ExtractionResult:
    """
    Full Stage 4 + 5 pipeline.
    Loads pending feedback, classifies in batches, applies validation routing,
    persists Labels, and updates run counters.
    """
    # ── Load enum config ──────────────────────────────────────────────────────
    if enum_config is None:
        enum_config = await get_latest_enum_config(run_id, session)

    if not enum_config:
        raise EnumConfigError(
            f"No enum config found for run {run_id}. Run discovery first."
        )

    allowed_keys = get_allowed_keys(enum_config)
    if not allowed_keys:
        raise EnumConfigError("Enum config has no categories.")

    BatchModel = _build_batch_model(allowed_keys)

    # ── Load pending feedback ─────────────────────────────────────────────────
    pending: list[RawFeedback] = list(
        (
            await session.execute(
                select(RawFeedback)
                .where(
                    RawFeedback.run_id == run_id,
                    RawFeedback.status == FeedbackStatus.PENDING,
                )
                .order_by(RawFeedback.created_at)
            )
        ).scalars().all()
    )

    if not pending:
        logger.warning("No pending items for run %s", run_id)
        return ExtractionResult(
            run_id=run_id,
            total_items=0,
            processed_items=0,
            flagged_items=0,
            error_items=0,
            actual_cost_usd=0.0,
            enum_config_version=enum_config.version,
        )

    total = len(pending)
    logger.info("Starting extraction for run %s: %d items, %d categories", run_id, total, len(allowed_keys))

    # Update run status
    run = await session.get(Run, run_id)
    if run:
        run.status = RunStatus.EXTRACTING
        await session.commit()

    project_id = run.project_id if run else None
    extraction_system = await get_prompt(session, "extraction_system", project_id)

    # ── Build categories description for prompt ───────────────────────────────
    from grainsift.engine.discovery import enum_config_to_categories
    categories = enum_config_to_categories(enum_config)
    categories_json = json.dumps(
        [{"key": c.key, "label": c.label, "description": c.description} for c in categories],
        ensure_ascii=False,
    )

    # ── Group multi-chunk rows into processing units ──────────────────────────
    units = _build_processing_units(pending)
    logger.info(
        "Extraction units for run %s: %d (from %d DB rows, %d multi-chunk groups collapsed)",
        run_id, len(units), total, total - len(units),
    )

    # ── Process in batches ────────────────────────────────────────────────────
    progress = ExtractionProgress(total_items=len(units))
    unit_batches = _make_batches(units, settings.batch_size)

    # Accumulate per-category confidence for adaptive stats
    cat_confidence_sum: dict[str, float] = defaultdict(float)
    cat_confidence_count: dict[str, int] = defaultdict(int)

    from grainsift.models.enums import ReviewFlag

    for batch_idx, batch in enumerate(unit_batches):
        items_json = json.dumps(
            [{"index": i, "text": unit.text} for i, unit in enumerate(batch)],
            ensure_ascii=False,
        )

        messages = [
            {"role": "system", "content": extraction_system},
            {
                "role": "user",
                "content": EXTRACTION.user(
                    n=len(batch),
                    categories_json=categories_json,
                    items_json=items_json,
                ),
            },
        ]

        schema_retried = False
        try:
            result = await llm.complete(
                messages=messages,
                response_model=BatchModel,
                max_retries=2,
            )
            labels_data = result.labels  # type: ignore[attr-defined]
        except LLMValidationError:
            schema_retried = True
            labels_data = _make_fallback_labels(len(batch), allowed_keys)
        except LLMError as exc:
            logger.error("LLM error on batch %d: %s", batch_idx, exc)
            progress.errors += len(batch)
            err_flagged: list[str] = []
            err_processed: list[str] = []
            for unit in batch:
                await _save_label(
                    session=session,
                    feedback=unit.primary,
                    category="other",
                    sentiment=Sentiment.NEUTRAL,
                    urgency=Urgency.MEDIUM,
                    key_phrase=None,
                    confidence=0.0,
                    review_flags=["schema_retry"],
                    source=LabelSource.LLM,
                    llm_category="other",
                )
                err_flagged.append(unit.primary.id)
                err_processed.extend(sib.id for sib in unit.siblings)
            if err_flagged:
                await session.execute(
                    update(RawFeedback)
                    .where(RawFeedback.id.in_(err_flagged))
                    .values(status=FeedbackStatus.FLAGGED)
                )
            if err_processed:
                await session.execute(
                    update(RawFeedback)
                    .where(RawFeedback.id.in_(err_processed))
                    .values(status=FeedbackStatus.PROCESSED)
                )
            await session.flush()
            continue

        # Accumulate token cost (approximate)
        input_toks = _PROMPT_OVERHEAD_TOKENS + len(batch) * _AVG_FEEDBACK_TOKENS
        output_toks = len(batch) * _AVG_OUTPUT_TOKENS
        progress.actual_cost_usd += llm.estimate_cost(input_toks, output_toks)

        # ── Adaptive batch check: if batch mean confidence is very low, flag all ─
        batch_confidences = [
            float(lbl.confidence)
            for lbl in (labels_data or [])  # type: ignore[union-attr]
            if hasattr(lbl, "confidence")
        ]
        batch_mean_confidence = sum(batch_confidences) / len(batch_confidences) if batch_confidences else 1.0
        batch_uncertain = batch_mean_confidence < settings.confidence_threshold * 0.9

        # ── Process each label in this batch ──────────────────────────────────
        label_map = {lbl.item_index: lbl for lbl in labels_data}  # type: ignore[union-attr]

        flagged_ids: list[str] = []
        processed_ids: list[str] = []

        for local_idx, unit in enumerate(batch):
            label_data = label_map.get(local_idx)
            if label_data is None:
                progress.errors += 1
                flagged_ids.append(unit.primary.id)
                processed_ids.extend(sib.id for sib in unit.siblings)
                continue

            category_str = str(label_data.category.value if hasattr(label_data.category, "value") else label_data.category)
            confidence = float(label_data.confidence)
            sentiment_str = str(label_data.sentiment.value if hasattr(label_data.sentiment, "value") else label_data.sentiment)
            urgency_str = str(label_data.urgency.value if hasattr(label_data.urgency, "value") else label_data.urgency)

            # Track per-category confidence
            cat_confidence_sum[category_str] += confidence
            cat_confidence_count[category_str] += 1

            flags = get_review_flags(
                category=category_str,
                confidence=confidence,
                urgency=urgency_str,
                char_count=unit.primary.char_count,
                language=unit.primary.language,
                language_confidence=unit.primary.language_confidence,
                schema_retried=schema_retried,
                settings=settings,
            )

            # Whole-batch uncertainty: add flag if not already present
            if batch_uncertain and ReviewFlag.LOW_CONFIDENCE not in flags:
                flags.append(ReviewFlag.LOW_CONFIDENCE)

            if is_random_sample(0.05) and ReviewFlag.RANDOM_SAMPLE not in flags:
                flags.append(ReviewFlag.RANDOM_SAMPLE)

            queued = needs_human_review(flags)

            await _save_label(
                session=session,
                feedback=unit.primary,
                category=category_str,
                sentiment=sentiment_str,
                urgency=urgency_str,
                key_phrase=label_data.key_phrase,
                confidence=confidence,
                review_flags=[f.value for f in flags],
                source=LabelSource.LLM,
                llm_category=category_str,
            )

            if queued:
                flagged_ids.append(unit.primary.id)
                progress.flagged += 1
            else:
                processed_ids.append(unit.primary.id)
            progress.processed += 1

            processed_ids.extend(sib.id for sib in unit.siblings)

        # Use direct SQL UPDATE to guarantee the status is written — ORM
        # attribute assignment on objects loaded earlier in the session can
        # silently lose the change when the session is flushed mid-loop.
        if flagged_ids:
            await session.execute(
                update(RawFeedback)
                .where(RawFeedback.id.in_(flagged_ids))
                .values(status=FeedbackStatus.FLAGGED)
            )
        if processed_ids:
            await session.execute(
                update(RawFeedback)
                .where(RawFeedback.id.in_(processed_ids))
                .values(status=FeedbackStatus.PROCESSED)
            )

        await session.flush()

        # Commit every 3 batches so the polling endpoint sees live progress
        if (batch_idx + 1) % 3 == 0:
            if run:
                run.processed_rows = progress.processed
                run.flagged_rows = progress.flagged
                run.actual_cost = round(progress.actual_cost_usd, 6)
            await session.commit()

        if (batch_idx + 1) % 10 == 0:
            logger.info(
                "Extraction progress run %s: %d/%d (%.0f%%)",
                run_id, progress.processed, len(units), progress.pct_complete,
            )

    # ── Identify systematically low-confidence categories ─────────────────────
    low_confidence_categories = [
        cat
        for cat, count in cat_confidence_count.items()
        if count >= 3 and (cat_confidence_sum[cat] / count) < settings.confidence_threshold
    ]

    # ── Finalize run ──────────────────────────────────────────────────────────
    await session.commit()

    if run:
        run.processed_rows = progress.processed
        run.flagged_rows = progress.flagged
        run.actual_cost = round(progress.actual_cost_usd, 6)
        run.enum_version = enum_config.version
        run.model_used = llm.model_name
        run.status = RunStatus.COMPLETE
        from datetime import UTC, datetime
        run.completed_at = datetime.now(UTC)
        await session.commit()

    if low_confidence_categories:
        logger.warning(
            "Low-confidence categories for run %s: %s",
            run_id, ", ".join(low_confidence_categories),
        )

    logger.info(
        "Extraction complete for run %s: %d processed, %d flagged, $%.4f cost",
        run_id, progress.processed, progress.flagged, progress.actual_cost_usd,
    )

    return ExtractionResult(
        run_id=run_id,
        total_items=len(units),
        processed_items=progress.processed,
        flagged_items=progress.flagged,
        error_items=progress.errors,
        actual_cost_usd=round(progress.actual_cost_usd, 6),
        enum_config_version=enum_config.version,
        low_confidence_categories=low_confidence_categories,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_batches(items: list[Any], batch_size: int) -> list[list[Any]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def _make_fallback_labels(count: int, allowed_keys: list[str]) -> list[Any]:
    """Produce stub labels that flag every item for review when LLM validation fails."""
    from types import SimpleNamespace

    fallback_category = allowed_keys[0] if allowed_keys else "other"
    return [
        SimpleNamespace(
            item_index=i,
            category=SimpleNamespace(value=fallback_category),
            sentiment=SimpleNamespace(value=Sentiment.NEUTRAL),
            urgency=SimpleNamespace(value=Urgency.MEDIUM),
            key_phrase=None,
            confidence=0.0,
        )
        for i in range(count)
    ]


async def _save_label(
    session: AsyncSession,
    feedback: RawFeedback,
    category: str,
    sentiment: str,
    urgency: str,
    key_phrase: str | None,
    confidence: float,
    review_flags: list[str],
    source: LabelSource,
    llm_category: str,
) -> Label:
    label = Label(
        feedback_id=feedback.id,
        category=category,
        sentiment=sentiment,
        urgency=urgency,
        key_phrase=key_phrase,
        confidence=confidence,
        source=source,
        llm_category=llm_category,
        review_flags=review_flags if review_flags else None,
    )
    session.add(label)
    return label
