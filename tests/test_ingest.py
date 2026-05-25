"""Tests for the ingest engine (Stage 1)."""

from __future__ import annotations

import io

import pytest

from grainsift.config import Settings
from grainsift.engine.ingest import (
    _chunk_text,
    _content_hash,
    _detect_language,
    _normalize_text,
    _strip_pii,
    ingest_csv,
    preview_csv,
)
from grainsift.models.database import Run
from grainsift.models.enums import FeedbackStatus, RunStatus
from grainsift.models.schemas import ColumnMapping


# ─── Unit tests for pure helpers ─────────────────────────────────────────────


def test_normalize_text_strips_whitespace():
    assert _normalize_text("  hello   world  ") == "hello world"


def test_normalize_text_strips_surrounding_quotes():
    assert _normalize_text('"hello world"') == "hello world"


def test_normalize_text_unicode():
    # NFKC normalization collapses ligatures
    assert _normalize_text("ﬁle") == "file"


def test_content_hash_case_insensitive():
    assert _content_hash("Hello World") == _content_hash("hello world")


def test_strip_pii_email():
    text, count = _strip_pii("Contact me at user@example.com for details")
    assert "[EMAIL]" in text
    assert "user@example.com" not in text
    assert count == 1


def test_strip_pii_phone():
    text, count = _strip_pii("Call me at 555-867-5309 anytime")
    assert "[PHONE]" in text
    assert count == 1


def test_strip_pii_ssn():
    text, count = _strip_pii("My SSN is 123-45-6789")
    assert "[SSN]" in text
    assert count == 1


def test_strip_pii_no_false_positives():
    clean = "The app has great UX and the team is responsive"
    text, count = _strip_pii(clean)
    assert text == clean
    assert count == 0


def test_chunk_text_short_text_is_unchanged():
    text = "This is a short piece of feedback"
    chunks = _chunk_text(text, max_words=400, overlap_words=50)
    assert chunks == [text]


def test_chunk_text_long_text_produces_multiple_chunks():
    words = ["word"] * 500
    text = " ".join(words)
    chunks = _chunk_text(text, max_words=200, overlap_words=50)
    assert len(chunks) >= 2
    # Each chunk is at most max_words words
    for chunk in chunks:
        assert len(chunk.split()) <= 200


def test_chunk_text_overlap():
    words = [f"w{i}" for i in range(300)]
    text = " ".join(words)
    chunks = _chunk_text(text, max_words=100, overlap_words=20)
    # The start of chunk N+1 should overlap with the end of chunk N
    assert len(chunks) >= 2


# ─── preview_csv ─────────────────────────────────────────────────────────────


def test_preview_csv_returns_columns_and_rows(sample_csv_bytes):
    columns, rows, count = preview_csv(sample_csv_bytes)
    assert "feedback" in columns
    assert len(rows) == 5
    assert count > 5


def test_preview_csv_invalid_file():
    from grainsift.exceptions import IngestError

    with pytest.raises(IngestError):
        preview_csv(b"not,a,valid\x00csv\xff\xfe")


# ─── ingest_csv integration tests ────────────────────────────────────────────


@pytest.fixture
async def run(db_session) -> Run:
    r = Run(filename="test.csv", status=RunStatus.PENDING)
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_provider="anthropic",
        database_url="sqlite+aiosqlite:///:memory:",
    )


async def test_ingest_csv_accepts_valid_rows(db_session, run, settings, sample_csv_bytes):
    mapping = ColumnMapping(
        feedback_column="feedback",
        date_column="date",
        source_column="source",
    )
    result = await ingest_csv(
        run_id=run.id,
        content=sample_csv_bytes,
        column_mapping=mapping,
        session=db_session,
        settings=settings,
    )
    assert result.total_rows > 0
    assert result.accepted_rows > 0
    assert result.run_id == run.id


async def test_ingest_csv_deduplicates_within_run(db_session, run, settings):
    csv = b"feedback\n" + b"This is a duplicate row.\n" * 5
    mapping = ColumnMapping(feedback_column="feedback")
    result = await ingest_csv(
        run_id=run.id,
        content=csv,
        column_mapping=mapping,
        session=db_session,
        settings=settings,
    )
    assert result.accepted_rows == 1
    assert result.duplicate_rows == 4


async def test_ingest_csv_skips_too_short(db_session, run, settings):
    csv = b"feedback\nok\nyes\nno\nThis is long enough to pass the minimum word check.\n"
    mapping = ColumnMapping(feedback_column="feedback")
    result = await ingest_csv(
        run_id=run.id,
        content=csv,
        column_mapping=mapping,
        session=db_session,
        settings=settings,
    )
    assert result.skipped_rows >= 3
    assert result.accepted_rows == 1


async def test_ingest_csv_strips_pii(db_session, run, settings):
    from sqlalchemy import select

    from grainsift.models.database import RawFeedback

    csv = b"feedback\nContact support at help@company.com for billing issues.\n"
    mapping = ColumnMapping(feedback_column="feedback")
    await ingest_csv(
        run_id=run.id,
        content=csv,
        column_mapping=mapping,
        session=db_session,
        settings=settings,
    )
    rows = (
        await db_session.execute(
            select(RawFeedback).where(RawFeedback.run_id == run.id)
        )
    ).scalars().all()
    assert rows
    assert "help@company.com" not in rows[0].clean_text


async def test_ingest_csv_missing_column_raises(db_session, run, settings, sample_csv_bytes):
    from grainsift.exceptions import IngestError

    mapping = ColumnMapping(feedback_column="nonexistent_column")
    with pytest.raises(IngestError, match="not found in CSV"):
        await ingest_csv(
            run_id=run.id,
            content=sample_csv_bytes,
            column_mapping=mapping,
            session=db_session,
            settings=settings,
        )


async def test_ingest_csv_persists_status_pending(db_session, run, settings, sample_csv_bytes):
    from sqlalchemy import select

    from grainsift.models.database import RawFeedback

    mapping = ColumnMapping(
        feedback_column="feedback",
        date_column="date",
        source_column="source",
    )
    await ingest_csv(
        run_id=run.id,
        content=sample_csv_bytes,
        column_mapping=mapping,
        session=db_session,
        settings=settings,
    )
    rows = (
        await db_session.execute(
            select(RawFeedback).where(RawFeedback.run_id == run.id)
        )
    ).scalars().all()
    assert all(r.status == FeedbackStatus.PENDING for r in rows)
