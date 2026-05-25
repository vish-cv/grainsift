"""Human review queue routes (Stage 6)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from grainsift.api.deps import DbSession
from grainsift.engine.aggregation import get_review_queue
from grainsift.models.database import Correction, Label, RawFeedback
from grainsift.models.enums import FeedbackStatus, LabelSource, Sentiment, Urgency
from grainsift.models.schemas import ReviewDecision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs/{run_id}/review", tags=["review"])


class ReviewQueueResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class ReviewStats(BaseModel):
    total_flagged: int
    reviewed: int
    pending_review: int
    pct_complete: float


class BulkReviewBody(BaseModel):
    label_ids: list[str]
    action: str  # confirm | edit
    corrected_category: str | None = None
    corrected_sentiment: Sentiment | None = None
    corrected_urgency: Urgency | None = None


@router.get("", response_model=ReviewQueueResponse)
async def get_review_items(
    run_id: str,
    db: DbSession,
    page: int = 0,
    page_size: int = 20,
) -> ReviewQueueResponse:
    """
    Return the human review queue for a run.
    Items are sorted: high urgency first, lowest confidence first within urgency.
    """
    items, total = await get_review_queue(
        run_id=run_id,
        session=db,
        page=page,
        page_size=page_size,
    )
    return ReviewQueueResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=ReviewStats)
async def get_review_stats(run_id: str, db: DbSession) -> ReviewStats:
    """Current review queue progress for a run."""
    from sqlalchemy import func

    total_flagged: int = (
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

    reviewed: int = (
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
    pct = round(reviewed / total_flagged * 100, 1) if total_flagged else 100.0

    return ReviewStats(
        total_flagged=total_flagged,
        reviewed=reviewed,
        pending_review=pending,
        pct_complete=pct,
    )


@router.post("/decision", status_code=204)
async def submit_decision(
    run_id: str,
    body: ReviewDecision,
    db: DbSession,
) -> None:
    """
    Submit a review decision for one item.
    action: "confirm" | "edit" | "skip"
    """
    label = await db.get(Label, body.label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Label {body.label_id} not found")

    feedback = await db.get(RawFeedback, label.feedback_id)
    if not feedback or feedback.run_id != run_id:
        raise HTTPException(status_code=404, detail="Feedback not found in this run")

    if body.action == "skip":
        # Re-queue at the bottom — just return without marking reviewed
        return

    now = datetime.now(UTC)

    if body.action == "confirm":
        label.source = LabelSource.HUMAN
        label.reviewed_at = now
        label.reviewer_notes = body.reviewer_notes
        feedback.status = FeedbackStatus.PROCESSED

    elif body.action == "edit":
        if not any([body.corrected_category, body.corrected_sentiment, body.corrected_urgency]):
            raise HTTPException(
                status_code=422, detail="edit action requires at least one corrected field"
            )

        correction = Correction(
            label_id=label.id,
            original_category=label.category,
            corrected_category=body.corrected_category,
            original_sentiment=label.sentiment,
            corrected_sentiment=body.corrected_sentiment.value if body.corrected_sentiment else None,
            original_urgency=label.urgency,
            corrected_urgency=body.corrected_urgency.value if body.corrected_urgency else None,
        )
        db.add(correction)

        if body.corrected_category:
            label.category = body.corrected_category
        if body.corrected_sentiment:
            label.sentiment = body.corrected_sentiment.value
        if body.corrected_urgency:
            label.urgency = body.corrected_urgency.value

        label.source = LabelSource.HUMAN
        label.reviewed_at = now
        label.reviewer_notes = body.reviewer_notes
        feedback.status = FeedbackStatus.PROCESSED

    else:
        raise HTTPException(status_code=422, detail=f"Unknown action: {body.action}")

    await db.commit()


@router.post("/bulk", status_code=200)
async def bulk_review(
    run_id: str,
    body: BulkReviewBody,
    db: DbSession,
) -> dict[str, int]:
    """
    Apply the same confirm/edit action to multiple labels at once.
    Returns {applied: N} where N is the count of labels actually updated.
    """
    if not body.label_ids:
        raise HTTPException(status_code=422, detail="label_ids cannot be empty")
    if body.action == "edit" and not any(
        [body.corrected_category, body.corrected_sentiment, body.corrected_urgency]
    ):
        raise HTTPException(
            status_code=422, detail="edit action requires at least one corrected field"
        )
    if body.action not in ("confirm", "edit"):
        raise HTTPException(status_code=422, detail=f"Unknown action: {body.action}")

    now = datetime.now(UTC)
    applied = 0

    for label_id in body.label_ids:
        label = await db.get(Label, label_id)
        if not label:
            continue
        feedback = await db.get(RawFeedback, label.feedback_id)
        if not feedback or feedback.run_id != run_id:
            continue

        if body.action == "confirm":
            label.source = LabelSource.HUMAN
            label.reviewed_at = now
            feedback.status = FeedbackStatus.PROCESSED
            applied += 1

        elif body.action == "edit":
            correction = Correction(
                label_id=label.id,
                original_category=label.category,
                corrected_category=body.corrected_category,
                original_sentiment=label.sentiment,
                corrected_sentiment=body.corrected_sentiment.value if body.corrected_sentiment else None,
                original_urgency=label.urgency,
                corrected_urgency=body.corrected_urgency.value if body.corrected_urgency else None,
            )
            db.add(correction)
            if body.corrected_category:
                label.category = body.corrected_category
            if body.corrected_sentiment:
                label.sentiment = body.corrected_sentiment.value
            if body.corrected_urgency:
                label.urgency = body.corrected_urgency.value
            label.source = LabelSource.HUMAN
            label.reviewed_at = now
            feedback.status = FeedbackStatus.PROCESSED
            applied += 1

    await db.commit()
    return {"applied": applied}
