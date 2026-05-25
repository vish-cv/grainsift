"""Dashboard and aggregation routes (Stage 7)."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from grainsift.api.deps import DbSession
from grainsift.engine.aggregation import (
    compute_attention_signals,
    compute_category_accuracy,
    compute_dashboard_stats,
    compute_keyphrase_clusters,
    compute_timeseries,
)
from grainsift.models.database import Label, RawFeedback, Run
from grainsift.models.schemas import DashboardStats

router = APIRouter(prefix="/runs/{run_id}/dashboard", tags=["dashboard"])


class LabeledItem(BaseModel):
    id: str
    text: str
    language: str | None
    source_channel: str | None
    date: str | None
    category: str
    sentiment: str
    urgency: str
    key_phrase: str | None
    confidence: float
    source: str
    review_flags: list[str]


class LabelsPage(BaseModel):
    items: list[LabeledItem]
    total: int
    page: int
    page_size: int


@router.get("", response_model=DashboardStats)
async def get_dashboard(run_id: str, db: DbSession) -> DashboardStats:
    """Return aggregated statistics for a run's labels."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return await compute_dashboard_stats(run_id=run_id, session=db)


@router.get("/attention")
async def get_attention(run_id: str, db: DbSession) -> dict[str, Any]:
    """
    Priority signals: briefing line, top-3 attention cards, unified category table, verbatim quotes.
    All derived from labeled data — no LLM.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return await compute_attention_signals(run_id, db)


@router.get("/accuracy")
async def get_accuracy(run_id: str, db: DbSession) -> dict[str, Any]:
    """
    Per-category accuracy based on human corrections.
    Returns empty dict if no human reviews exist yet.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    accuracy = await compute_category_accuracy(run_id=run_id, session=db)
    return {
        "run_id": run_id,
        "per_category": accuracy,
        "overall": round(sum(accuracy.values()) / len(accuracy), 3) if accuracy else None,
    }


@router.get("/labels", response_model=LabelsPage)
async def get_labels(
    run_id: str,
    db: DbSession,
    page: int = 0,
    page_size: int = 50,
    search: str | None = None,
    category: str | None = None,
    sentiment: str | None = None,
    urgency: str | None = None,
) -> LabelsPage:
    """Return paginated labeled items with optional filters."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    conditions = [RawFeedback.run_id == run_id]
    if search:
        conditions.append(RawFeedback.original_text.ilike(f"%{search}%"))
    if category:
        conditions.append(Label.category == category)
    if sentiment:
        conditions.append(Label.sentiment == sentiment)
    if urgency:
        conditions.append(Label.urgency == urgency)

    total = (
        await db.scalar(
            select(func.count())
            .select_from(Label)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(*conditions)
        )
    ) or 0

    rows = (
        await db.execute(
            select(
                RawFeedback.id,
                RawFeedback.original_text,
                RawFeedback.language,
                RawFeedback.source_channel,
                RawFeedback.feedback_date,
                Label.category,
                Label.sentiment,
                Label.urgency,
                Label.key_phrase,
                Label.confidence,
                Label.source,
                Label.review_flags,
            )
            .join(Label, Label.feedback_id == RawFeedback.id)
            .where(*conditions)
            .order_by(Label.urgency.desc(), RawFeedback.feedback_date)
            .offset(page * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        LabeledItem(
            id=r.id,
            text=r.original_text,
            language=r.language,
            source_channel=r.source_channel,
            date=r.feedback_date.isoformat() if r.feedback_date else None,
            category=r.category,
            sentiment=r.sentiment,
            urgency=r.urgency,
            key_phrase=r.key_phrase,
            confidence=r.confidence,
            source=r.source,
            review_flags=r.review_flags or [],
        )
        for r in rows
    ]

    return LabelsPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/keyphrases")
async def get_keyphrases(run_id: str, db: DbSession) -> list[dict[str, Any]]:
    """
    Top recurring key phrases per category.
    No LLM — counts existing key_phrase values from labels.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return await compute_keyphrase_clusters(run_id, db)


@router.get("/timeseries")
async def get_timeseries(run_id: str, db: DbSession) -> list[dict[str, Any]]:
    """
    Feedback volume by day (uses feedback_date from ingest).
    Returns [{date, total, by_category: {cat: count}}] sorted by date.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return await compute_timeseries(run_id, db)


@router.get("/export/csv")
async def export_labels_csv(run_id: str, db: DbSession) -> StreamingResponse:
    """
    Export all labeled feedback as a CSV.
    Columns: feedback_id, original_text, category, sentiment, urgency,
             key_phrase, confidence, source, review_flags, date
    """
    from sqlalchemy import select

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    rows = (
        await db.execute(
            select(
                RawFeedback.id,
                RawFeedback.original_text,
                RawFeedback.language,
                RawFeedback.source_channel,
                RawFeedback.feedback_date,
                Label.category,
                Label.sentiment,
                Label.urgency,
                Label.key_phrase,
                Label.confidence,
                Label.source,
                Label.review_flags,
            )
            .join(Label, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id)
            .order_by(Label.urgency.desc(), RawFeedback.feedback_date)
        )
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "feedback_id", "original_text", "language", "source_channel",
        "date", "category", "sentiment", "urgency", "key_phrase",
        "confidence", "source", "review_flags",
    ])
    for row in rows:
        writer.writerow([
            row.id, row.original_text, row.language, row.source_channel,
            row.feedback_date.isoformat() if row.feedback_date else "",
            row.category, row.sentiment, row.urgency, row.key_phrase or "",
            f"{row.confidence:.3f}", row.source,
            "|".join(row.review_flags) if row.review_flags else "",
        ])

    buf.seek(0)
    filename = f"grainsift_{run_id[:8]}_labels.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
