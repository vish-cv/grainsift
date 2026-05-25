"""Tests for the aggregation engine (Stage 7)."""

from __future__ import annotations

import pytest

from grainsift.engine.aggregation import compute_dashboard_stats, get_review_queue
from grainsift.models.database import EnumConfig, Label, RawFeedback, Run
from grainsift.models.enums import FeedbackStatus, LabelSource, RunStatus


@pytest.fixture
async def labeled_run(db_session):
    """A run with 6 labeled items covering different categories/sentiments/urgencies."""
    run = Run(filename="agg_test.csv", status=RunStatus.COMPLETE)
    db_session.add(run)
    await db_session.flush()

    items = [
        ("App crashes on checkout", "app_stability", "negative", "high", 0.92, FeedbackStatus.PROCESSED),
        ("Billing charged twice", "billing", "negative", "high", 0.88, FeedbackStatus.FLAGGED),
        ("Love the new dashboard", "ux", "positive", "low", 0.95, FeedbackStatus.PROCESSED),
        ("Search broken on mobile", "app_stability", "negative", "medium", 0.72, FeedbackStatus.PROCESSED),
        ("Dark mode please", "feature_request", "neutral", "low", 0.85, FeedbackStatus.PROCESSED),
        ("Great support team", "support", "positive", "low", 0.91, FeedbackStatus.PROCESSED),
    ]

    for text, category, sentiment, urgency, conf, status in items:
        feedback = RawFeedback(
            run_id=run.id,
            original_text=text,
            clean_text=text,
            content_hash=f"hash_{text[:8]}",
            char_count=len(text),
            word_count=len(text.split()),
            status=status,
        )
        db_session.add(feedback)
        await db_session.flush()

        label = Label(
            feedback_id=feedback.id,
            category=category,
            sentiment=sentiment,
            urgency=urgency,
            confidence=conf,
            source=LabelSource.LLM,
            llm_category=category,
        )
        db_session.add(label)

    await db_session.commit()
    return run


# ─── compute_dashboard_stats ──────────────────────────────────────────────────


async def test_dashboard_stats_total_count(db_session, labeled_run):
    stats = await compute_dashboard_stats(labeled_run.id, db_session)
    assert stats.total_labeled == 6


async def test_dashboard_stats_volume_by_category(db_session, labeled_run):
    stats = await compute_dashboard_stats(labeled_run.id, db_session)
    cats = {c.category: c.count for c in stats.volume_by_category}
    assert cats["app_stability"] == 2
    assert cats["billing"] == 1
    assert cats["ux"] == 1


async def test_dashboard_stats_sentiment_breakdown(db_session, labeled_run):
    stats = await compute_dashboard_stats(labeled_run.id, db_session)
    app_stability = next(
        (s for s in stats.sentiment_by_category if s.category == "app_stability"), None
    )
    assert app_stability is not None
    assert app_stability.negative == 2


async def test_dashboard_stats_urgency(db_session, labeled_run):
    stats = await compute_dashboard_stats(labeled_run.id, db_session)
    urgency_map = {u.urgency: u.count for u in stats.urgency_distribution}
    assert urgency_map.get("high", 0) == 2
    assert urgency_map.get("low", 0) >= 3


async def test_dashboard_stats_empty_run(db_session):
    run = Run(filename="empty.csv", status=RunStatus.PENDING)
    db_session.add(run)
    await db_session.commit()

    stats = await compute_dashboard_stats(run.id, db_session)
    assert stats.total_labeled == 0
    assert stats.volume_by_category == []


# ─── get_review_queue ─────────────────────────────────────────────────────────


async def test_review_queue_returns_flagged_items(db_session, labeled_run):
    items, total = await get_review_queue(labeled_run.id, db_session)
    # Only the item with FeedbackStatus.FLAGGED should appear
    assert total == 1
    assert len(items) == 1
    assert items[0]["suggested_category"] == "billing"


async def test_review_queue_pagination(db_session, labeled_run):
    items, total = await get_review_queue(labeled_run.id, db_session, page=0, page_size=1)
    assert len(items) == 1
    assert total == 1


async def test_review_queue_empty_when_all_processed(db_session):
    run = Run(filename="done.csv", status=RunStatus.COMPLETE)
    db_session.add(run)
    await db_session.commit()

    items, total = await get_review_queue(run.id, db_session)
    assert total == 0
    assert items == []
