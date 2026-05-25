"""Query Engine — natural language Q&A over labeled feedback (structured RAG)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.engine.prompt_store import get_prompt
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.models.database import Label, QueryMessage, RawFeedback, Run

logger = logging.getLogger(__name__)

_MAX_CONTEXT_ITEMS = 40
_FULL_SCAN_THRESHOLD = 250
_MAX_PRIOR_TURNS = 5

_STOPWORDS: set[str] = {
    "what", "why", "how", "when", "where", "who", "which", "are", "is",
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
    "do", "does", "did", "can", "could", "would", "should", "tell",
    "me", "my", "our", "their", "about", "and", "or", "but", "most",
    "more", "less", "many", "some", "any", "all", "show", "give", "list",
    "users", "user", "customers", "customer", "people", "they", "feedback",
}


class QuerySource(BaseModel):
    text: str = Field(description="Direct quote from the user feedback — copy exactly as written")
    category: str = Field(description="The category label of this feedback item")
    sentiment: str = Field(description="The sentiment label: positive, negative, neutral, or mixed")
    urgency: str = Field(description="The urgency label: high, medium, or low")
    why_relevant: str = Field(description="One sentence: why this specific quote supports the answer")


class QueryAnswer(BaseModel):
    answer: str = Field(description="Direct 2-3 sentence answer to the question, grounded in the data")
    key_insights: list[str] = Field(
        description="3 to 5 specific, data-backed bullet points. Each must reference actual numbers, categories, or patterns.",
        min_length=2,
        max_length=5,
    )
    sources: list[QuerySource] = Field(
        description="3 to 5 representative feedback quotes that directly support the answer",
        min_length=1,
        max_length=5,
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="How well the available data addresses this question"
    )


# ─── Aggregate stats context ──────────────────────────────────────────────────


async def _build_stats_context(run_id: str, session: AsyncSession) -> str:
    rows = (
        await session.execute(
            select(
                Label.category,
                Label.sentiment,
                Label.urgency,
                func.count().label("cnt"),
            )
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(RawFeedback.run_id == run_id)
            .group_by(Label.category, Label.sentiment, Label.urgency)
        )
    ).all()

    if not rows:
        return ""

    cat_counts: dict[str, int] = {}
    sentiment_counts: dict[str, int] = {}
    urgency_counts: dict[str, int] = {}
    total = 0

    for r in rows:
        cat_counts[r.category] = cat_counts.get(r.category, 0) + r.cnt
        sentiment_counts[r.sentiment] = sentiment_counts.get(r.sentiment, 0) + r.cnt
        urgency_counts[r.urgency] = urgency_counts.get(r.urgency, 0) + r.cnt
        total += r.cnt

    top_cats = sorted(cat_counts.items(), key=lambda x: -x[1])[:8]
    cat_lines = ", ".join(f"{cat} ({cnt})" for cat, cnt in top_cats)

    neg = sentiment_counts.get("negative", 0)
    pos = sentiment_counts.get("positive", 0)
    neu = sentiment_counts.get("neutral", 0)
    mixed = sentiment_counts.get("mixed", 0)
    hi = urgency_counts.get("high", 0)
    med = urgency_counts.get("medium", 0)
    lo = urgency_counts.get("low", 0)

    lines = [
        f"Total labeled items: {total}",
        f"Top categories by volume: {cat_lines}",
        f"Sentiment: {neg} negative ({round(neg/total*100)}%), "
        f"{pos} positive ({round(pos/total*100)}%), "
        f"{neu} neutral ({round(neu/total*100)}%)"
        + (f", {mixed} mixed" if mixed else ""),
        f"Urgency: {hi} high, {med} medium, {lo} low",
    ]
    return "\n".join(lines)


# ─── Session helpers ──────────────────────────────────────────────────────────


async def _load_session_context(
    run_id: str,
    session_id: str,
    session: AsyncSession,
) -> list[dict]:
    rows = (
        await session.execute(
            select(QueryMessage.question, QueryMessage.answer)
            .where(
                QueryMessage.run_id == run_id,
                QueryMessage.session_id == session_id,
            )
            .order_by(QueryMessage.created_at.desc())
            .limit(_MAX_PRIOR_TURNS)
        )
    ).all()

    return [{"question": r.question, "answer": r.answer} for r in reversed(rows)]


async def _save_query_message(
    run_id: str,
    session_id: str,
    question: str,
    answer: QueryAnswer,
    session: AsyncSession,
) -> str:
    msg = QueryMessage(
        run_id=run_id,
        session_id=session_id,
        question=question,
        answer=answer.answer,
        key_insights=answer.key_insights,
        sources=[s.model_dump() for s in answer.sources],
        confidence=answer.confidence,
    )
    session.add(msg)
    await session.commit()
    return msg.id


# ─── Retrieval ────────────────────────────────────────────────────────────────


def _extract_keywords(question: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{3,}\b", question.lower())
    return [w for w in words if w not in _STOPWORDS][:8]


async def _retrieve_items(
    run_id: str,
    question: str,
    session: AsyncSession,
) -> list[dict]:
    cols = (
        RawFeedback.original_text,
        RawFeedback.language,
        Label.category,
        Label.sentiment,
        Label.urgency,
        Label.confidence,
        Label.key_phrase,
    )
    base_where = RawFeedback.run_id == run_id

    total = (
        await session.scalar(
            select(func.count())
            .select_from(Label)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(base_where)
        )
    ) or 0

    if total == 0:
        return []

    if total <= _FULL_SCAN_THRESHOLD:
        rows = (
            await session.execute(
                select(*cols)
                .join(Label, Label.feedback_id == RawFeedback.id)
                .where(base_where)
                .order_by(Label.urgency.desc(), Label.confidence.desc())
                .limit(_MAX_CONTEXT_ITEMS)
            )
        ).all()
    else:
        keywords = _extract_keywords(question)
        kw_rows: list = []
        if keywords:
            kw_rows = (
                await session.execute(
                    select(*cols)
                    .join(Label, Label.feedback_id == RawFeedback.id)
                    .where(
                        base_where,
                        or_(*[RawFeedback.original_text.ilike(f"%{kw}%") for kw in keywords]),
                    )
                    .order_by(Label.urgency.desc(), Label.confidence.desc())
                    .limit(_MAX_CONTEXT_ITEMS // 2)
                )
            ).all()

        high_rows = (
            await session.execute(
                select(*cols)
                .join(Label, Label.feedback_id == RawFeedback.id)
                .where(base_where, Label.urgency == "high")
                .order_by(Label.confidence.desc())
                .limit(_MAX_CONTEXT_ITEMS // 2)
            )
        ).all()

        seen: set[str] = set()
        merged: list = []
        for r in [*kw_rows, *high_rows]:
            if r.original_text not in seen:
                seen.add(r.original_text)
                merged.append(r)
        rows = merged[:_MAX_CONTEXT_ITEMS]

    return [
        {
            "text": r.original_text,
            "category": r.category,
            "sentiment": r.sentiment,
            "urgency": r.urgency,
            "confidence": round(r.confidence, 2),
            "key_phrase": r.key_phrase,
        }
        for r in rows
    ]


# ─── Main entry point ─────────────────────────────────────────────────────────


async def answer_question(
    run_id: str,
    question: str,
    session: AsyncSession,
    llm: BaseLLMProvider,
    session_id: str | None = None,
) -> tuple[QueryAnswer, str]:
    """
    Answer a question grounded in the run's labeled data.
    Returns (answer, session_id). Saves the exchange to the DB.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    run = await session.get(Run, run_id)
    system_prompt = await get_prompt(session, "query_system", run.project_id if run else None)

    stats_context = await _build_stats_context(run_id, session)
    prior_turns = await _load_session_context(run_id, session_id, session)
    items = await _retrieve_items(run_id, question, session)

    if not items:
        raise ValueError("No labeled items found — run extraction first.")

    items_block = "\n".join(
        f'[{i}] [{r["category"]} | {r["sentiment"]} | urgency:{r["urgency"]}] '
        f'"{r["text"]}"'
        + (f' (key phrase: {r["key_phrase"]})' if r.get("key_phrase") else "")
        for i, r in enumerate(items, 1)
    )

    prior_block = ""
    if prior_turns:
        lines: list[str] = []
        for turn in prior_turns:
            lines.append(f"Q: {turn['question']}")
            lines.append(f"A: {turn['answer']}")
        prior_block = "\n\n## Prior conversation\n" + "\n\n".join(lines)

    user_content = (
        f"## Dataset overview\n{stats_context}"
        f"{prior_block}"
        f"\n\n## Feedback items ({len(items)} items)\n{items_block}"
        f"\n\n## Question\n{question}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info(
        "Query engine: run=%s session=%s prior_turns=%d context_items=%d",
        run_id, session_id, len(prior_turns), len(items),
    )

    answer = await llm.complete(messages=messages, response_model=QueryAnswer)
    await _save_query_message(run_id, session_id, question, answer, session)

    return answer, session_id


# ─── History ──────────────────────────────────────────────────────────────────


async def get_query_history(run_id: str, session: AsyncSession) -> list[dict]:
    """
    All Q&A sessions for a run. Sessions newest first, messages oldest first.
    """
    rows = (
        await session.execute(
            select(QueryMessage)
            .where(QueryMessage.run_id == run_id)
            .order_by(QueryMessage.created_at.asc())
        )
    ).scalars().all()

    sessions: dict[str, list[dict]] = {}
    session_started_at: dict[str, str] = {}

    for msg in rows:
        sid = msg.session_id
        if sid not in sessions:
            sessions[sid] = []
            session_started_at[sid] = msg.created_at.isoformat()
        sessions[sid].append({
            "id": msg.id,
            "question": msg.question,
            "answer": msg.answer,
            "key_insights": msg.key_insights or [],
            "sources": msg.sources or [],
            "confidence": msg.confidence,
            "created_at": msg.created_at.isoformat(),
        })

    result = [
        {"session_id": sid, "started_at": session_started_at[sid], "messages": msgs}
        for sid, msgs in sessions.items()
    ]
    result.sort(key=lambda s: s["started_at"], reverse=True)
    return result
