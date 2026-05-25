"""
Stage 7 — Aggregation Engine.

Pure pandas. No LLM. Computes dashboard statistics from the labels table.
All functions are async at the DB layer but compute in-process with pandas.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.models.database import Correction, Label, RawFeedback
from grainsift.models.enums import LabelSource
from grainsift.models.schemas import (
    CategoryCount,
    DashboardStats,
    SentimentBreakdown,
    UrgencyCount,
)

logger = logging.getLogger(__name__)


async def compute_dashboard_stats(
    run_id: str,
    session: AsyncSession,
) -> DashboardStats:
    """
    Compute all dashboard metrics for a run.
    Joins labels → raw_feedback to pull category, sentiment, urgency, and date.
    """
    rows = (
        await session.execute(
            select(
                Label.category,
                Label.sentiment,
                Label.urgency,
                Label.confidence,
                Label.source,
                RawFeedback.feedback_date,
            )
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id)
        )
    ).all()

    if not rows:
        return DashboardStats(
            run_id=run_id,
            total_labeled=0,
            human_reviewed=0,
            auto_labeled=0,
            volume_by_category=[],
            sentiment_by_category=[],
            urgency_distribution=[],
            other_volume=0,
            other_pct=0.0,
        )

    df = pd.DataFrame(rows, columns=["category", "sentiment", "urgency", "confidence", "source", "date"])

    total = len(df)
    human_reviewed = int((df["source"] == LabelSource.HUMAN).sum())
    auto_labeled = total - human_reviewed

    # ── Volume by category ────────────────────────────────────────────────────
    volume_series = df["category"].value_counts()
    volume_by_category = [
        CategoryCount(category=cat, count=int(count))
        for cat, count in volume_series.items()
    ]

    # ── Sentiment breakdown per category ──────────────────────────────────────
    sentiment_pivot = (
        df.groupby(["category", "sentiment"])
        .size()
        .unstack(fill_value=0)
    )
    sentiment_cols = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
    sentiment_by_category: list[SentimentBreakdown] = []
    for cat in sentiment_pivot.index:
        row_data = sentiment_pivot.loc[cat].to_dict()
        sentiment_by_category.append(
            SentimentBreakdown(
                category=str(cat),
                positive=int(row_data.get("positive", 0)),
                negative=int(row_data.get("negative", 0)),
                neutral=int(row_data.get("neutral", 0)),
                mixed=int(row_data.get("mixed", 0)),
            )
        )

    # ── Urgency distribution ──────────────────────────────────────────────────
    urgency_series = df["urgency"].value_counts()
    urgency_distribution = [
        UrgencyCount(urgency=urg, count=int(count))
        for urg, count in urgency_series.items()
    ]

    # ── Other category tracking ───────────────────────────────────────────────
    other_volume = int((df["category"] == "other").sum())
    other_pct = round(other_volume / total * 100, 1) if total > 0 else 0.0

    return DashboardStats(
        run_id=run_id,
        total_labeled=total,
        human_reviewed=human_reviewed,
        auto_labeled=auto_labeled,
        volume_by_category=volume_by_category,
        sentiment_by_category=sentiment_by_category,
        urgency_distribution=urgency_distribution,
        other_volume=other_volume,
        other_pct=other_pct,
    )


async def compute_category_accuracy(
    run_id: str,
    session: AsyncSession,
) -> dict[str, float]:
    """
    For items that were human-reviewed, what fraction did the LLM get right?
    Returns {category: accuracy_0_to_1}.
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
        return {}

    df = pd.DataFrame(rows, columns=["original", "corrected"])

    accuracy: dict[str, float] = {}
    for cat, group in df.groupby("original"):
        correct = (group["corrected"].isna() | (group["corrected"] == group["original"])).sum()
        accuracy[str(cat)] = round(float(correct) / len(group), 3)

    return accuracy


async def get_review_queue(
    run_id: str,
    session: AsyncSession,
    page: int = 0,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    Return flagged items sorted by urgency (high first) then confidence (low first).
    Returns (items, total_count).
    """
    from sqlalchemy import func

    total: int = (
        await session.scalar(
            select(func.count())
            .select_from(Label)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                func.json_array_length(Label.review_flags) > 0,
                Label.reviewed_at.is_(None),
            )
        )
    ) or 0

    rows = (
        await session.execute(
            select(Label, RawFeedback)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                func.json_array_length(Label.review_flags) > 0,
                Label.reviewed_at.is_(None),
            )
            .order_by(
                # high urgency first
                Label.urgency.desc(),
                # lowest confidence first within same urgency
                Label.confidence.asc(),
            )
            .offset(page * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        {
            "feedback_id": r.RawFeedback.id,
            "original_text": r.RawFeedback.original_text,
            "translated_text": r.RawFeedback.translated_text,
            "language": r.RawFeedback.language,
            "label_id": r.Label.id,
            "suggested_category": r.Label.category,
            "suggested_sentiment": r.Label.sentiment,
            "suggested_urgency": r.Label.urgency,
            "key_phrase": r.Label.key_phrase,
            "confidence": r.Label.confidence,
            "review_flags": r.Label.review_flags or [],
        }
        for r in rows
    ]

    return items, total


async def compute_keyphrase_clusters(
    run_id: str,
    session: AsyncSession,
    top_n: int = 5,
) -> list[dict]:
    """
    Count key_phrase occurrences per category.
    Returns [{category, phrases: [{phrase, count}]}] sorted by category volume.
    Only includes categories with at least 2 labeled phrases.
    """
    rows = (
        await session.execute(
            select(Label.category, Label.key_phrase)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                Label.key_phrase.is_not(None),
                Label.category != "other",
            )
        )
    ).all()

    cat_phrases: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        phrase = (row.key_phrase or "").strip().lower()
        if phrase:
            cat_phrases[row.category].append(phrase)

    result = []
    for cat, phrases in cat_phrases.items():
        if len(phrases) < 2:
            continue
        top = Counter(phrases).most_common(top_n)
        result.append({
            "category": cat,
            "phrases": [{"phrase": p, "count": c} for p, c in top],
        })

    result.sort(key=lambda x: -sum(p["count"] for p in x["phrases"]))
    return result


async def compute_attention_signals(run_id: str, session: AsyncSession) -> dict:
    """
    Derive priority signals from labeled data — no LLM.
    Returns: briefing line, top-3 attention cards, unified category table, verbatim quotes.
    """
    rows = (
        await session.execute(
            select(
                Label.category,
                Label.sentiment,
                Label.urgency,
                Label.confidence,
                Label.key_phrase,
                RawFeedback.original_text,
            )
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id)
        )
    ).all()

    empty = {
        "total_labeled": 0, "briefing": "", "attention": [],
        "category_table": [], "verbatim": {},
    }
    if not rows:
        return empty

    df = pd.DataFrame(rows, columns=["category", "sentiment", "urgency", "confidence", "key_phrase", "text"])
    total = len(df)

    # ── Per-category metrics (excluding "other") ──────────────────────────────
    cat_metrics: dict[str, dict] = {}
    for cat, group in df[df["category"] != "other"].groupby("category"):
        cat_total = len(group)
        neg = int((group["sentiment"] == "negative").sum())
        pos = int((group["sentiment"] == "positive").sum())
        neu = int((group["sentiment"] == "neutral").sum())
        high = int((group["urgency"] == "high").sum())
        neg_pct = neg / cat_total
        high_pct = high / cat_total
        priority = round(neg_pct * 0.5 + high_pct * 0.5, 3)

        phrases = group["key_phrase"].dropna().str.strip().str.lower()
        mode_result = phrases.mode()
        top_phrase = str(mode_result.iloc[0]) if len(mode_result) > 0 else None

        # Prefer high-urgency + negative items for verbatim quotes
        subset = group[(group["sentiment"] == "negative") | (group["urgency"] == "high")]
        verbatim = (subset["text"].head(2) if len(subset) > 0 else group["text"].head(2)).tolist()

        cat_metrics[str(cat)] = {
            "category": str(cat), "count": cat_total,
            "positive": pos, "negative": neg, "neutral": neu,
            "negative_pct": round(neg_pct * 100, 1),
            "high_urgency": high, "priority_score": priority,
            "top_phrase": top_phrase, "verbatim": verbatim,
        }

    # ── Other / unlabeled ─────────────────────────────────────────────────────
    other_count = int((df["category"] == "other").sum())
    other_pct = round(other_count / total * 100, 1) if total > 0 else 0.0

    # ── Overall stats for briefing ────────────────────────────────────────────
    overall_neg_pct = round(int((df["sentiment"] == "negative").sum()) / total * 100) if total > 0 else 0
    high_urg_total = int((df["urgency"] == "high").sum())
    sorted_cats = sorted(cat_metrics.values(), key=lambda x: -x["priority_score"])

    briefing_parts: list[str] = []
    if overall_neg_pct > 50:
        briefing_parts.append(f"{overall_neg_pct}% of feedback is negative")
    if sorted_cats:
        briefing_parts.append(f"{sorted_cats[0]['category'].replace('_', ' ')} is the top concern")
    if other_pct > 30:
        briefing_parts.append(f"{int(other_pct)}% couldn't be categorized")
    elif high_urg_total > 0:
        briefing_parts.append(f"{high_urg_total} items are high urgency")
    briefing = ". ".join(briefing_parts) + "." if briefing_parts else ""

    # ── Attention cards (max 3, high severity first) ──────────────────────────
    attention: list[dict] = []

    if other_pct > 30:
        attention.append({
            "type": "taxonomy_gap", "category": None,
            "title": f"{int(other_pct)}% unlabeled",
            "detail": f"{other_count} items have no category — taxonomy may need refinement",
            "action": "refine_taxonomy",
            "severity": "high" if other_pct >= 50 else "medium",
            "count": other_count,
        })

    for m in sorted_cats:
        if len(attention) >= 3:
            break
        detail_parts = []
        if m["negative_pct"] >= 80:
            detail_parts.append(f"{int(m['negative_pct'])}% negative")
        if m["high_urgency"] > 0:
            detail_parts.append(f"{m['high_urgency']} high urgency")
        if m["top_phrase"]:
            detail_parts.append(f'"{m["top_phrase"]}"')
        attention.append({
            "type": "category", "category": m["category"],
            "title": m["category"].replace("_", " "),
            "detail": " · ".join(detail_parts) if detail_parts else f"{m['count']} items",
            "action": "review_items",
            "severity": "high" if m["priority_score"] >= 0.7 else "medium",
            "count": m["count"],
        })

    attention.sort(key=lambda x: 0 if x["severity"] == "high" else 1)

    # ── Category table (all categories, other at bottom) ──────────────────────
    category_table = [
        {
            "category": m["category"], "count": m["count"],
            "positive": m["positive"], "negative": m["negative"], "neutral": m["neutral"],
            "negative_pct": m["negative_pct"], "high_urgency": m["high_urgency"],
            "top_phrase": m["top_phrase"], "priority_score": m["priority_score"],
        }
        for m in sorted(cat_metrics.values(), key=lambda x: -x["count"])
    ]
    if other_count > 0:
        og = df[df["category"] == "other"]
        category_table.append({
            "category": "other", "count": other_count,
            "positive": int((og["sentiment"] == "positive").sum()),
            "negative": int((og["sentiment"] == "negative").sum()),
            "neutral": int((og["sentiment"] == "neutral").sum()),
            "negative_pct": round(int((og["sentiment"] == "negative").sum()) / other_count * 100, 1),
            "high_urgency": int((og["urgency"] == "high").sum()),
            "top_phrase": None, "priority_score": 0.0,
        })

    return {
        "total_labeled": total,
        "briefing": briefing,
        "attention": attention,
        "category_table": category_table,
        "verbatim": {cat: m["verbatim"] for cat, m in cat_metrics.items()},
    }


async def compute_timeseries(
    run_id: str,
    session: AsyncSession,
) -> list[dict]:
    """
    Aggregate label counts by date (day) and category.
    Returns [{date, total, by_category: {cat: count}}] sorted by date.
    Only rows where feedback_date is not null are included.
    """
    rows = (
        await session.execute(
            select(
                func.date(RawFeedback.feedback_date).label("day"),
                Label.category,
                func.count().label("cnt"),
            )
            .join(Label, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                RawFeedback.feedback_date.is_not(None),
            )
            .group_by(func.date(RawFeedback.feedback_date), Label.category)
            .order_by(func.date(RawFeedback.feedback_date))
        )
    ).all()

    date_map: dict[str, dict] = {}
    for row in rows:
        day = str(row.day)
        if day not in date_map:
            date_map[day] = {"date": day, "total": 0, "by_category": {}}
        date_map[day]["total"] += row.cnt
        date_map[day]["by_category"][row.category] = row.cnt

    return list(date_map.values())
