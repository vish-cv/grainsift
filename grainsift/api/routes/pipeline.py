"""Pipeline audit trail endpoint — per-stage visibility for a run."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from grainsift.api.deps import DbSession
from grainsift.engine.discovery import enum_config_to_categories, get_latest_enum_config
from grainsift.models.database import Label, RawFeedback, Run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs/{run_id}/pipeline", tags=["pipeline"])


# ─── Response models ──────────────────────────────────────────────────────────


class IngestStage(BaseModel):
    total_rows: int
    accepted_rows: int
    duplicate_rows: int
    skipped_rows: int
    pii_redactions: int
    pii_types: dict[str, int]
    non_english_rows: int
    language_distribution: dict[str, int]
    column_warnings: list[str] = Field(default_factory=list)


class DiscoveryCategory(BaseModel):
    key: str
    label: str
    description: str


class DiscoveryStage(BaseModel):
    version: int
    category_count: int
    categories: list[DiscoveryCategory]
    created_by: str


class ExtractionStage(BaseModel):
    processed: int
    flagged: int
    auto_confirmed: int
    actual_cost_usd: float | None
    model: str | None
    flag_breakdown: dict[str, int]
    low_confidence_categories: list[str] = Field(default_factory=list)


class ReviewStage(BaseModel):
    total_flagged: int
    reviewed: int
    pending: int
    pct_complete: float


class PipelineResponse(BaseModel):
    run_id: str
    run_status: str
    filename: str
    ingest: IngestStage | None
    discovery: DiscoveryStage | None
    extraction: ExtractionStage | None
    review: ReviewStage | None


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("", response_model=PipelineResponse)
async def get_pipeline(run_id: str, db: DbSession) -> PipelineResponse:
    """
    Return a complete per-stage audit trail for a run.
    Used by the Pipeline page to show what each engine stage did.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # ── Stage 1: Ingest ───────────────────────────────────────────────────────
    ingest: IngestStage | None = None
    if run.summary:
        try:
            raw = json.loads(run.summary)
            ingest = IngestStage(
                total_rows=raw.get("total_rows", 0),
                accepted_rows=raw.get("accepted_rows", 0),
                duplicate_rows=raw.get("duplicate_rows", 0),
                skipped_rows=raw.get("skipped_rows", 0),
                pii_redactions=raw.get("pii_redactions", 0),
                pii_types=raw.get("pii_types", {}),
                non_english_rows=raw.get("non_english_rows", 0),
                language_distribution=raw.get("language_distribution", {}),
                column_warnings=raw.get("column_warnings", []),
            )
        except Exception:
            pass

    # ── Stage 2: Discovery ────────────────────────────────────────────────────
    discovery: DiscoveryStage | None = None
    enum_config = await get_latest_enum_config(run_id, db)
    if enum_config:
        cats = enum_config_to_categories(enum_config)
        discovery = DiscoveryStage(
            version=enum_config.version,
            category_count=len(cats),
            categories=[DiscoveryCategory(key=c.key, label=c.label, description=c.description) for c in cats],
            created_by=enum_config.created_by,
        )

    # ── Stage 3: Extraction + Validation ─────────────────────────────────────
    extraction: ExtractionStage | None = None
    if run.processed_rows is not None and run.processed_rows > 0:
        # Aggregate flag breakdown from labels
        flag_rows = (
            await db.execute(
                select(Label.review_flags)
                .join(RawFeedback, Label.feedback_id == RawFeedback.id)
                .where(RawFeedback.run_id == run_id, Label.review_flags.is_not(None))
            )
        ).scalars().all()

        flag_breakdown: dict[str, int] = {}
        for flags in flag_rows:
            if flags:
                for flag in flags:
                    flag_breakdown[flag] = flag_breakdown.get(flag, 0) + 1

        total_labeled = (
            await db.scalar(
                select(func.count())
                .select_from(Label)
                .join(RawFeedback, Label.feedback_id == RawFeedback.id)
                .where(RawFeedback.run_id == run_id)
            )
        ) or 0

        # Per-category mean confidence — flag any category consistently below threshold
        from grainsift.config import get_settings as _get_settings
        _threshold = _get_settings().confidence_threshold
        cat_conf_rows = (
            await db.execute(
                select(Label.category, func.avg(Label.confidence).label("avg_conf"), func.count().label("cnt"))
                .join(RawFeedback, Label.feedback_id == RawFeedback.id)
                .where(RawFeedback.run_id == run_id)
                .group_by(Label.category)
            )
        ).all()
        low_confidence_categories = [
            row.category
            for row in cat_conf_rows
            if row.cnt >= 3 and (row.avg_conf or 1.0) < _threshold
        ]

        extraction = ExtractionStage(
            processed=run.processed_rows,
            flagged=run.flagged_rows or 0,
            auto_confirmed=total_labeled - (run.flagged_rows or 0),
            actual_cost_usd=run.actual_cost,
            model=run.model_used,
            flag_breakdown=flag_breakdown,
            low_confidence_categories=low_confidence_categories,
        )

    # ── Stage 4: Review ───────────────────────────────────────────────────────
    review: ReviewStage | None = None
    if run.processed_rows and run.processed_rows > 0:
        total_flagged = (
            await db.scalar(
                select(func.count())
                .select_from(Label)
                .join(RawFeedback, Label.feedback_id == RawFeedback.id)
                .where(
                    RawFeedback.run_id == run_id,
                    func.json_array_length(Label.review_flags) > 0,
                )
            )
        ) or 0

        if total_flagged > 0:
            reviewed = (
                await db.scalar(
                    select(func.count())
                    .select_from(Label)
                    .join(RawFeedback, Label.feedback_id == RawFeedback.id)
                    .where(
                        RawFeedback.run_id == run_id,
                        func.json_array_length(Label.review_flags) > 0,
                        Label.reviewed_at.is_not(None),
                    )
                )
            ) or 0

            pending = total_flagged - reviewed
            pct = round(reviewed / total_flagged * 100, 1)
            review = ReviewStage(
                total_flagged=total_flagged,
                reviewed=reviewed,
                pending=pending,
                pct_complete=pct,
            )

    return PipelineResponse(
        run_id=run_id,
        run_status=run.status,
        filename=run.filename,
        ingest=ingest,
        discovery=discovery,
        extraction=extraction,
        review=review,
    )
