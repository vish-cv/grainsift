"""Tests for the validation routing engine (Stage 5)."""

from __future__ import annotations

from grainsift.config import Settings
from grainsift.engine.validation import get_review_flags, needs_human_review
from grainsift.models.enums import ReviewFlag, Urgency


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        confidence_threshold=0.65,
        **overrides,
    )


def test_low_confidence_flag():
    flags = get_review_flags(
        category="billing",
        confidence=0.40,
        urgency=Urgency.LOW,
        char_count=100,
        language="en",
        language_confidence=0.99,
        schema_retried=False,
        settings=_settings(),
    )
    assert ReviewFlag.LOW_CONFIDENCE in flags


def test_no_flag_above_threshold():
    flags = get_review_flags(
        category="billing",
        confidence=0.90,
        urgency=Urgency.LOW,
        char_count=100,
        language="en",
        language_confidence=0.99,
        schema_retried=False,
        settings=_settings(),
    )
    assert flags == []


def test_other_category_flag():
    flags = get_review_flags(
        category="other",
        confidence=0.80,
        urgency=Urgency.LOW,
        char_count=100,
        language="en",
        language_confidence=0.99,
        schema_retried=False,
        settings=_settings(),
    )
    assert ReviewFlag.CATEGORY_OTHER in flags


def test_short_text_flag():
    flags = get_review_flags(
        category="billing",
        confidence=0.90,
        urgency=Urgency.LOW,
        char_count=10,
        language="en",
        language_confidence=0.99,
        schema_retried=False,
        settings=_settings(),
    )
    assert ReviewFlag.SHORT_TEXT in flags


def test_schema_retry_flag():
    flags = get_review_flags(
        category="billing",
        confidence=0.90,
        urgency=Urgency.LOW,
        char_count=100,
        language="en",
        language_confidence=0.99,
        schema_retried=True,
        settings=_settings(),
    )
    assert ReviewFlag.SCHEMA_RETRY in flags


def test_language_flag_non_english():
    flags = get_review_flags(
        category="billing",
        confidence=0.90,
        urgency=Urgency.LOW,
        char_count=100,
        language="fr",
        language_confidence=0.95,
        schema_retried=False,
        settings=_settings(),
    )
    assert ReviewFlag.LANGUAGE_FLAG in flags


def test_high_urgency_low_confidence_flag():
    flags = get_review_flags(
        category="billing",
        confidence=0.40,
        urgency=Urgency.HIGH,
        char_count=100,
        language="en",
        language_confidence=0.99,
        schema_retried=False,
        settings=_settings(),
    )
    assert ReviewFlag.HIGH_URGENCY_LOW_CONFIDENCE in flags or ReviewFlag.LOW_CONFIDENCE in flags


def test_needs_human_review_two_flags():
    flags = [ReviewFlag.LOW_CONFIDENCE, ReviewFlag.SHORT_TEXT]
    assert needs_human_review(flags) is True


def test_no_review_needed_zero_flags():
    assert needs_human_review([]) is False


def test_no_review_needed_one_minor_flag():
    # Single LOW_CONFIDENCE alone doesn't queue (threshold is 2 flags or 1 critical)
    assert needs_human_review([ReviewFlag.LOW_CONFIDENCE]) is False


def test_single_critical_flag_triggers_review():
    assert needs_human_review([ReviewFlag.SCHEMA_RETRY]) is True
    assert needs_human_review([ReviewFlag.LANGUAGE_FLAG]) is True
    assert needs_human_review([ReviewFlag.HIGH_URGENCY_LOW_CONFIDENCE]) is True
