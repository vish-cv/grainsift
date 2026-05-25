"""
Stage 1 — Ingestion and Normalization.

Reads a CSV file, normalizes text, deduplicates, strips PII,
detects language, chunks long items, and persists to raw_feedback.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.config import Settings
from grainsift.exceptions import IngestError
from grainsift.models.database import RawFeedback, Run
from grainsift.models.enums import FeedbackStatus
from grainsift.models.schemas import ColumnMapping

logger = logging.getLogger(__name__)

# ─── PII patterns (regex-based, no external dependency) ──────────────────────

_PII_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]", "email"),
    (
        re.compile(
            r"\b(\+?\d{1,3}[\s\-.]?)?"
            r"(\(?\d{3}\)?[\s\-.]?)"
            r"\d{3}[\s\-.]?\d{4}\b"
        ),
        "[PHONE]",
        "phone",
    ),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]", "ssn"),
    (re.compile(r"\b\d{16}\b"), "[CARD]", "card_number"),
    # IPv4 addresses — valid octet ranges (0-255)
    (
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        "[IP]",
        "ip_address",
    ),
    # US-style street addresses: "123 Main Street", "456 Oak Ave Apt 2"
    (
        re.compile(
            r"\b\d+\s+[A-Za-z]+(?:\s+[A-Za-z]+)*\s+"
            r"(?:Street|Avenue|Boulevard|Drive|Road|Lane|Way|Court|Place|Terrace|Parkway|"
            r"St|Ave|Blvd|Dr|Rd|Ln|Ct|Pl|Ter|Pkwy)\b\.?",
            re.IGNORECASE,
        ),
        "[ADDRESS]",
        "address",
    ),
    # Names preceded by common honorifics: "Mr. Smith", "Dr. Johnson", "Mrs Williams"
    (
        re.compile(
            r"\b(?:Mr|Mrs|Ms|Dr|Prof|Miss|Rev)\.?\s+[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?\b"
        ),
        "[NAME]",
        "name",
    ),
]

_FEEDBACK_COLUMN_KEYWORDS = frozenset({
    "feedback", "comment", "review", "text", "message",
    "body", "note", "content", "response", "description",
})


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class IngestResult:
    run_id: str
    total_rows: int = 0
    accepted_rows: int = 0
    duplicate_rows: int = 0
    skipped_rows: int = 0
    pii_redactions: int = 0
    pii_types: dict[str, int] = field(default_factory=dict)
    non_english_rows: int = 0
    language_distribution: dict[str, int] = field(default_factory=dict)
    column_warnings: list[str] = field(default_factory=list)


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Unicode-normalize, collapse whitespace, strip surrounding quotes."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    # strip surrounding quotes that CSV parsers sometimes leave
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.lower().encode()).hexdigest()


def _strip_pii(text: str) -> tuple[str, int, dict[str, int]]:
    """Return (redacted_text, total_count, per_type_counts)."""
    count = 0
    type_counts: dict[str, int] = {}
    for pattern, replacement, pii_type in _PII_PATTERNS:
        new_text, n = pattern.subn(replacement, text)
        text = new_text
        count += n
        if n > 0:
            type_counts[pii_type] = type_counts.get(pii_type, 0) + n
    return text, count, type_counts


def _word_count(text: str) -> int:
    return len(text.split())


def _detect_language(text: str) -> tuple[str, float]:
    """Return (language_code, confidence). Falls back to 'unknown' on error."""
    try:
        from langdetect import detect_langs
        from langdetect.lang_detect_exception import LangDetectException

        results = detect_langs(text)
        if results:
            top = results[0]
            return top.lang, round(top.prob, 3)
    except Exception:  # noqa: BLE001
        pass
    return "unknown", 0.0


def _chunk_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    """
    Split text into overlapping word-boundary chunks.
    Tries to split on sentence endings first.
    """
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk_words = words[start:end]
        chunk = " ".join(chunk_words)

        # nudge end back to nearest sentence boundary if not at the end
        if end < len(words):
            # find last sentence-ending punctuation in chunk
            for i in range(len(chunk_words) - 1, max(len(chunk_words) - 20, -1), -1):
                if chunk_words[i].rstrip().endswith((".", "!", "?")):
                    chunk = " ".join(chunk_words[: i + 1])
                    end = start + i + 1
                    break

        chunks.append(chunk)

        if end >= len(words):
            break  # covered all words

        next_start = end - overlap_words
        if next_start <= start:
            break  # no forward progress — shouldn't happen, but guard anyway
        start = next_start

    return chunks


def _parse_date(value: object) -> datetime | None:
    """Best-effort date parsing. Returns None rather than raising."""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    if isinstance(value, pd.Timestamp):
        ts = value.to_pydatetime()
        return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
    try:
        return pd.to_datetime(str(value), utc=True).to_pydatetime()
    except Exception:  # noqa: BLE001
        return None


# ─── Preview ─────────────────────────────────────────────────────────────────


def preview_csv(content: bytes) -> tuple[list[str], list[dict[str, object]], int]:
    """
    Parse just enough of the CSV to return columns, first 5 rows, and row count.
    Returns (columns, preview_rows, estimated_row_count).
    """
    try:
        df_head = pd.read_csv(io.BytesIO(content), nrows=5, dtype=str)
        df_count = pd.read_csv(io.BytesIO(content), usecols=[0], dtype=str)
    except Exception as exc:
        raise IngestError(f"Could not parse CSV: {exc}") from exc

    columns = df_head.columns.tolist()
    preview_rows = df_head.fillna("").to_dict(orient="records")
    return columns, preview_rows, len(df_count)


# ─── Main ingest function ─────────────────────────────────────────────────────


async def ingest_csv(
    run_id: str,
    content: bytes,
    column_mapping: ColumnMapping,
    session: AsyncSession,
    settings: Settings,
) -> IngestResult:
    """
    Full Stage 1 pipeline. Reads CSV bytes, processes every row,
    and bulk-inserts into raw_feedback. Updates run counters on completion.
    """
    result = IngestResult(run_id=run_id)

    # ── Parse CSV ─────────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(io.BytesIO(content), dtype=str)
    except Exception as exc:
        raise IngestError(f"Could not parse CSV: {exc}") from exc

    if column_mapping.feedback_column not in df.columns:
        raise IngestError(
            f"Column '{column_mapping.feedback_column}' not found in CSV. "
            f"Available columns: {df.columns.tolist()}"
        )

    # ── Column validation warnings ────────────────────────────────────────────
    if column_mapping.date_column and column_mapping.date_column not in df.columns:
        result.column_warnings.append(
            f"Date column '{column_mapping.date_column}' was not found in the CSV — "
            f"feedback dates will be empty. "
            f"Available columns: {df.columns.tolist()}"
        )
    if column_mapping.source_column and column_mapping.source_column not in df.columns:
        result.column_warnings.append(
            f"Source column '{column_mapping.source_column}' was not found in the CSV — "
            f"source channel will be empty. "
            f"Available columns: {df.columns.tolist()}"
        )
    mapped_cols = {
        c for c in [
            column_mapping.feedback_column,
            column_mapping.date_column,
            column_mapping.source_column,
        ]
        if c
    }
    for col in df.columns:
        if col in mapped_cols:
            continue
        col_key = col.lower().replace(" ", "_").replace("-", "_")
        if any(kw in col_key for kw in _FEEDBACK_COLUMN_KEYWORDS):
            result.column_warnings.append(
                f"Column '{col}' looks like it may contain additional feedback text "
                f"but is not mapped. Re-upload with this column selected if needed."
            )

    result.total_rows = len(df)
    logger.info("Starting ingest for run %s: %d rows", run_id, result.total_rows)

    # ── Pre-load existing hashes for this run (deduplication) ─────────────────
    existing_hashes: set[str] = set(
        row[0]
        for row in (
            await session.execute(
                select(RawFeedback.content_hash).where(
                    RawFeedback.run_id == run_id
                )
            )
        ).all()
    )

    batch_hashes: set[str] = set()
    records: list[RawFeedback] = []

    for _, row in df.iterrows():
        raw_text = str(row.get(column_mapping.feedback_column, "") or "").strip()

        if not raw_text or raw_text.lower() in ("nan", "none", "null"):
            result.skipped_rows += 1
            continue

        # ── Normalize ─────────────────────────────────────────────────────────
        clean = _normalize_text(raw_text)

        # ── Skip too-short items ──────────────────────────────────────────────
        if _word_count(clean) < settings.min_feedback_words:
            result.skipped_rows += 1
            continue

        # ── Deduplication ─────────────────────────────────────────────────────
        content_hash = _content_hash(clean)
        if content_hash in existing_hashes or content_hash in batch_hashes:
            result.duplicate_rows += 1
            continue
        batch_hashes.add(content_hash)

        # ── PII stripping ─────────────────────────────────────────────────────
        clean, redactions, pii_type_counts = _strip_pii(clean)
        result.pii_redactions += redactions
        for ptype, cnt in pii_type_counts.items():
            result.pii_types[ptype] = result.pii_types.get(ptype, 0) + cnt

        # ── Language detection ────────────────────────────────────────────────
        lang, lang_conf = _detect_language(clean)
        result.language_distribution[lang] = (
            result.language_distribution.get(lang, 0) + 1
        )
        if lang not in ("en", "unknown"):
            result.non_english_rows += 1

        # ── Translation (best-effort, non-English only) ───────────────────────
        translated_text: str | None = None
        if lang not in ("en", "unknown") and lang_conf >= 0.7:
            from grainsift.engine.language import translate_to_english
            translated_text = translate_to_english(clean, lang)

        # ── Date extraction ───────────────────────────────────────────────────
        feedback_date: datetime | None = None
        if column_mapping.date_column and column_mapping.date_column in df.columns:
            feedback_date = _parse_date(row.get(column_mapping.date_column))

        # ── Source channel ────────────────────────────────────────────────────
        source_channel: str | None = None
        if column_mapping.source_column and column_mapping.source_column in df.columns:
            src = str(row.get(column_mapping.source_column, "") or "").strip()
            if src and src.lower() not in ("nan", "none"):
                source_channel = src

        # ── Chunk if too long ─────────────────────────────────────────────────
        chunks = _chunk_text(clean, settings.max_feedback_words, settings.chunk_overlap_words)

        for idx, chunk in enumerate(chunks):
            records.append(
                RawFeedback(
                    run_id=run_id,
                    original_text=raw_text if idx == 0 else chunk,
                    clean_text=chunk,
                    # All chunks share the same hash so extraction can group them
                    content_hash=content_hash,
                    language=lang,
                    language_confidence=lang_conf,
                    # only carry translation on the first chunk — fragments aren't meaningful standalone
                    translated_text=translated_text if idx == 0 else None,
                    source_channel=source_channel,
                    feedback_date=feedback_date,
                    char_count=len(chunk),
                    word_count=_word_count(chunk),
                    chunk_index=idx,
                    total_chunks=len(chunks),
                    status=FeedbackStatus.PENDING,
                )
            )

        result.accepted_rows += 1

        # Flush in batches of 500 to avoid holding everything in memory
        if len(records) >= 500:
            session.add_all(records)
            await session.flush()
            records.clear()

    if records:
        session.add_all(records)
        await session.flush()

    # ── Update run counters ───────────────────────────────────────────────────
    run = await session.get(Run, run_id)
    if run:
        run.total_rows = result.total_rows
        run.skipped_rows = result.skipped_rows
        run.duplicate_rows = result.duplicate_rows
        # processed_rows and flagged_rows are updated by the extraction stage

    await session.commit()

    logger.info(
        "Ingest complete for run %s: %d accepted, %d duplicates, %d skipped",
        run_id,
        result.accepted_rows,
        result.duplicate_rows,
        result.skipped_rows,
    )
    return result
