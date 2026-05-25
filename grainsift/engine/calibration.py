"""
Calibration Runner — measures AI label quality using two independent signals:

1. Human validation accuracy — from Correction table (no LLM needed)
2. Self-consistency — re-labels a random sample and compares to originals (LLM call)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.engine.discovery import enum_config_to_categories, get_latest_enum_config
from grainsift.engine.extraction import _build_batch_model
from grainsift.engine.prompt_store import get_prompt
from grainsift.llm.prompts import EXTRACTION
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.models.database import CalibrationResult, Correction, Label, RawFeedback, Run

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_SIZE = 20


# ─── Response models ──────────────────────────────────────────────────────────

class CategoryHumanStat(BaseModel):
    category: str
    reviewed: int
    confirmed: int
    corrected: int
    accuracy: float


class CategoryConsistency(BaseModel):
    category: str
    matches: int
    total: int
    agreement: float


class ConfusionPair(BaseModel):
    from_cat: str
    to_cat: str
    count: int


class ConfidenceBucket(BaseModel):
    label: str
    count: int
    accuracy: float | None


class CalibrationReport(BaseModel):
    # Human review stats
    total_reviewed: int
    human_accuracy: float | None
    human_correction_rate: float | None
    per_category_human: list[CategoryHumanStat]

    # Confusion matrix (from human corrections)
    confusion_pairs: list[ConfusionPair] = []

    # Confidence calibration buckets
    confidence_buckets: list[ConfidenceBucket] = []

    # Self-consistency
    has_self_check: bool
    sample_size: int | None
    category_agreement: float | None
    sentiment_agreement: float | None
    urgency_agreement: float | None
    per_category_consistency: list[CategoryConsistency]
    calibrated_at: str | None


# ─── Human accuracy (from Correction table) ───────────────────────────────────

async def _compute_human_stats(
    run_id: str,
    session: AsyncSession,
) -> tuple[int, float | None, float | None, list[CategoryHumanStat]]:
    """
    Derive accuracy from human review corrections.
    A label is "confirmed" if the reviewer made no category change.
    Returns (total_reviewed, overall_accuracy, correction_rate, per_category).
    """
    rows = (
        await session.execute(
            select(
                Correction.original_category,
                Correction.corrected_category,
            )
            .join(Label, Correction.label_id == Label.id)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id)
        )
    ).all()

    if not rows:
        return 0, None, None, []

    # Group by original category
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"reviewed": 0, "confirmed": 0, "corrected": 0})
    for orig, corrected in rows:
        cat = orig or "other"
        stats[cat]["reviewed"] += 1
        if corrected is None or corrected == orig:
            stats[cat]["confirmed"] += 1
        else:
            stats[cat]["corrected"] += 1

    per_category = [
        CategoryHumanStat(
            category=cat,
            reviewed=s["reviewed"],
            confirmed=s["confirmed"],
            corrected=s["corrected"],
            accuracy=round(s["confirmed"] / s["reviewed"], 3) if s["reviewed"] else 0.0,
        )
        for cat, s in sorted(stats.items(), key=lambda x: -x[1]["reviewed"])
    ]

    total = len(rows)
    total_confirmed = sum(s["confirmed"] for s in stats.values())
    total_corrected = total - total_confirmed

    return (
        total,
        round(total_confirmed / total, 3),
        round(total_corrected / total, 3),
        per_category,
    )


# ─── Confusion matrix (from human corrections) ────────────────────────────────

async def _compute_confusion_matrix(
    run_id: str,
    session: AsyncSession,
) -> list[ConfusionPair]:
    """
    Which categories did humans correct to which?
    Only counts cases where corrected_category differs from original.
    """
    rows = (
        await session.execute(
            select(
                Correction.original_category,
                Correction.corrected_category,
                func.count().label("cnt"),
            )
            .join(Label, Correction.label_id == Label.id)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                Correction.corrected_category.is_not(None),
                Correction.corrected_category != Correction.original_category,
            )
            .group_by(Correction.original_category, Correction.corrected_category)
            .order_by(func.count().desc())
        )
    ).all()

    return [
        ConfusionPair(from_cat=row.original_category, to_cat=row.corrected_category, count=row.cnt)
        for row in rows
    ]


# ─── Confidence calibration buckets ───────────────────────────────────────────

_CONFIDENCE_BUCKETS = [
    ("<50%",   0.0,  0.5),
    ("50–70%", 0.5,  0.7),
    ("70–85%", 0.7,  0.85),
    ("85%+",   0.85, 1.01),
]


async def _compute_confidence_buckets(
    run_id: str,
    session: AsyncSession,
) -> list[ConfidenceBucket]:
    """
    For human-reviewed labels, group by confidence bucket and compute accuracy.
    A label is "confirmed" when there is no correction that changed the category.
    """
    rows = (
        await session.execute(
            select(
                Label.confidence,
                Correction.corrected_category,
                Correction.original_category,
            )
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .outerjoin(Correction, Correction.label_id == Label.id)
            .where(
                RawFeedback.run_id == run_id,
                Label.reviewed_at.is_not(None),
            )
        )
    ).all()

    counts: dict[str, int] = {}
    confirmed: dict[str, int] = {}
    for label_name, _, _ in _CONFIDENCE_BUCKETS:
        counts[label_name] = 0
        confirmed[label_name] = 0

    for conf, corrected_cat, orig_cat in rows:
        for label_name, lo, hi in _CONFIDENCE_BUCKETS:
            if lo <= (conf or 0.0) < hi:
                counts[label_name] += 1
                if corrected_cat is None or corrected_cat == orig_cat:
                    confirmed[label_name] += 1
                break

    return [
        ConfidenceBucket(
            label=label_name,
            count=counts[label_name],
            accuracy=round(confirmed[label_name] / counts[label_name], 3) if counts[label_name] > 0 else None,
        )
        for label_name, _, _ in _CONFIDENCE_BUCKETS
    ]


# ─── Self-consistency (re-labeling sample) ────────────────────────────────────

async def _run_self_consistency(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    sample_size: int,
) -> tuple[int, float, float, float, list[CategoryConsistency]]:
    """
    Re-label a random sample of items and compare to originals.
    Returns (actual_sample_size, category_agreement, sentiment_agreement,
             urgency_agreement, per_category_consistency).
    """
    # ── Fetch sample items ────────────────────────────────────────────────────
    rows = (
        await session.execute(
            select(
                RawFeedback.original_text,
                Label.category,
                Label.sentiment,
                Label.urgency,
            )
            .join(Label, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id, Label.category != "other")
            .order_by(func.random())
            .limit(sample_size)
        )
    ).all()

    if not rows:
        return 0, 0.0, 0.0, 0.0, []

    actual_n = len(rows)
    originals = [
        {"text": r.original_text, "category": r.category, "sentiment": r.sentiment, "urgency": r.urgency}
        for r in rows
    ]

    # ── Fetch taxonomy ────────────────────────────────────────────────────────
    enum_config = await get_latest_enum_config(run_id, session)
    if enum_config is None:
        raise ValueError("No taxonomy found for this run — run discovery first.")

    category_objs = enum_config_to_categories(enum_config)
    allowed_keys = [c.key for c in category_objs] + ["other"]

    categories_json = json.dumps(
        [{"key": c.key, "label": c.label, "description": c.description} for c in category_objs],
        ensure_ascii=False,
    )
    items_json = json.dumps(
        [{"index": i, "text": r["text"]} for i, r in enumerate(originals)],
        ensure_ascii=False,
    )

    # ── Re-label via LLM ─────────────────────────────────────────────────────
    BatchModel = _build_batch_model(allowed_keys)
    run = await session.get(Run, run_id)
    extraction_system = await get_prompt(session, "extraction_system", run.project_id if run else None)

    messages = [
        {"role": "system", "content": extraction_system},
        {
            "role": "user",
            "content": EXTRACTION.user(
                n=actual_n,
                categories_json=categories_json,
                items_json=items_json,
            ),
        },
    ]

    result = await llm.complete(messages=messages, response_model=BatchModel)
    relabeled = {lbl.item_index: lbl for lbl in result.labels}  # type: ignore[attr-defined]

    # ── Compare ───────────────────────────────────────────────────────────────
    cat_matches = 0
    sent_matches = 0
    urg_matches = 0
    per_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "total": 0})

    for i, orig in enumerate(originals):
        rl = relabeled.get(i)
        if rl is None:
            continue
        cat_hit = str(rl.category) == orig["category"]
        sent_hit = str(rl.sentiment) == orig["sentiment"]
        urg_hit = str(rl.urgency) == orig["urgency"]

        cat_matches += int(cat_hit)
        sent_matches += int(sent_hit)
        urg_matches += int(urg_hit)

        per_cat[orig["category"]]["total"] += 1
        per_cat[orig["category"]]["matches"] += int(cat_hit)

    compared = len([i for i in range(actual_n) if i in relabeled])
    compared = max(compared, 1)

    per_category_consistency = [
        CategoryConsistency(
            category=cat,
            matches=s["matches"],
            total=s["total"],
            agreement=round(s["matches"] / s["total"], 3) if s["total"] else 0.0,
        )
        for cat, s in sorted(per_cat.items(), key=lambda x: -x[1]["total"])
    ]

    return (
        actual_n,
        round(cat_matches / compared, 3),
        round(sent_matches / compared, 3),
        round(urg_matches / compared, 3),
        per_category_consistency,
    )


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_calibration_report(
    run_id: str,
    session: AsyncSession,
) -> CalibrationReport:
    """Return current calibration state — human stats + saved self-check (if any)."""
    total_reviewed, human_acc, correction_rate, per_cat_human = await _compute_human_stats(run_id, session)
    confusion_pairs = await _compute_confusion_matrix(run_id, session)
    confidence_buckets = await _compute_confidence_buckets(run_id, session)

    saved = (
        await session.scalar(
            select(CalibrationResult).where(CalibrationResult.run_id == run_id)
        )
    )

    if saved:
        per_cat_consistency = (
            [CategoryConsistency(**c) for c in json.loads(saved.per_category_json)]
            if saved.per_category_json
            else []
        )
        return CalibrationReport(
            total_reviewed=total_reviewed,
            human_accuracy=human_acc,
            human_correction_rate=correction_rate,
            per_category_human=per_cat_human,
            confusion_pairs=confusion_pairs,
            confidence_buckets=confidence_buckets,
            has_self_check=True,
            sample_size=saved.sample_size,
            category_agreement=saved.category_agreement,
            sentiment_agreement=saved.sentiment_agreement,
            urgency_agreement=saved.urgency_agreement,
            per_category_consistency=per_cat_consistency,
            calibrated_at=saved.created_at.isoformat(),
        )

    return CalibrationReport(
        total_reviewed=total_reviewed,
        human_accuracy=human_acc,
        human_correction_rate=correction_rate,
        per_category_human=per_cat_human,
        confusion_pairs=confusion_pairs,
        confidence_buckets=confidence_buckets,
        has_self_check=False,
        sample_size=None,
        category_agreement=None,
        sentiment_agreement=None,
        urgency_agreement=None,
        per_category_consistency=[],
        calibrated_at=None,
    )


async def run_calibration(
    run_id: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
) -> CalibrationReport:
    """Run self-consistency check, persist result, return full report."""
    n, cat_agr, sent_agr, urg_agr, per_cat = await _run_self_consistency(
        run_id, session, llm, sample_size
    )

    # Upsert — delete existing then insert fresh
    await session.execute(
        delete(CalibrationResult).where(CalibrationResult.run_id == run_id)
    )
    session.add(
        CalibrationResult(
            run_id=run_id,
            sample_size=n,
            category_agreement=cat_agr,
            sentiment_agreement=sent_agr,
            urgency_agreement=urg_agr,
            per_category_json=json.dumps([c.model_dump() for c in per_cat]),
        )
    )
    await session.commit()

    logger.info(
        "Calibration done for run %s: cat=%.0f%% sent=%.0f%% urg=%.0f%% (n=%d)",
        run_id, cat_agr * 100, sent_agr * 100, urg_agr * 100, n,
    )

    return await get_calibration_report(run_id, session)
