"""
Stage 5 — Validation and Confidence Routing.

Pure functions. No DB access. No LLM.
Takes a single extraction result + feedback metadata and decides
whether the item auto-saves or goes to the human review queue.
"""

from __future__ import annotations

import random

from grainsift.config import Settings
from grainsift.models.enums import ReviewFlag, Urgency


def get_review_flags(
    category: str,
    confidence: float,
    urgency: str,
    char_count: int,
    language: str | None,
    language_confidence: float | None,
    schema_retried: bool,
    settings: Settings,
) -> list[ReviewFlag]:
    """
    Evaluate all routing conditions and return the applicable flags.
    Callers decide what to do based on the flag list.
    """
    flags: list[ReviewFlag] = []

    if confidence < settings.confidence_threshold:
        flags.append(ReviewFlag.LOW_CONFIDENCE)

    if category == "other":
        flags.append(ReviewFlag.CATEGORY_OTHER)

    if char_count < 15:
        flags.append(ReviewFlag.SHORT_TEXT)

    if schema_retried:
        flags.append(ReviewFlag.SCHEMA_RETRY)

    # Flag non-English, unknown, or low-confidence language detection
    if language not in (None, "en") or (language_confidence is not None and language_confidence < 0.8):
        if language not in (None, "en"):
            flags.append(ReviewFlag.LANGUAGE_FLAG)

    if urgency == Urgency.HIGH and confidence < settings.confidence_threshold:
        # Only add if not already flagged for low confidence
        if ReviewFlag.HIGH_URGENCY_LOW_CONFIDENCE not in flags:
            flags.append(ReviewFlag.HIGH_URGENCY_LOW_CONFIDENCE)

    return flags


def needs_human_review(flags: list[ReviewFlag]) -> bool:
    """
    Route to human review if:
    - 2 or more flags are set, OR
    - a single critical flag (schema retry, language flag) is set
    """
    if len(flags) >= 2:
        return True
    if len(flags) == 1 and flags[0] in (
        ReviewFlag.SCHEMA_RETRY,
        ReviewFlag.LANGUAGE_FLAG,
        ReviewFlag.HIGH_URGENCY_LOW_CONFIDENCE,
    ):
        return True
    return False


def is_random_sample(sample_rate: float = 0.05) -> bool:
    """Returns True for ~sample_rate fraction of calls (5% by default)."""
    return random.random() < sample_rate
