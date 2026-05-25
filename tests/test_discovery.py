"""Tests for the discovery engine (Stage 3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from grainsift.engine.discovery import (
    _OTHER_CATEGORY,
    enum_config_to_categories,
    get_allowed_keys,
    get_latest_enum_config,
    run_discovery,
    save_enum_config,
)
from grainsift.exceptions import EnumConfigError
from grainsift.models.database import RawFeedback, Run
from grainsift.models.enums import EnumConfigSource, FeedbackStatus, RunStatus
from grainsift.models.schemas import EnumCategory


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def run_with_feedback(db_session):
    """A run with 10 pending feedback rows."""
    run = Run(filename="test.csv", status=RunStatus.PENDING)
    db_session.add(run)
    await db_session.flush()

    texts = [
        "The app crashes on checkout",
        "Billing issue, charged twice",
        "Delivery was super fast, loved it",
        "Search doesn't work on mobile",
        "Dark mode please!",
        "App crashed again, third time this week",
        "Great onboarding experience",
        "Refund not processed after 3 weeks",
        "Push notifications broken on Android",
        "Checkout is seamless, great UX",
    ]
    for text in texts:
        db_session.add(
            RawFeedback(
                run_id=run.id,
                original_text=text,
                clean_text=text,
                content_hash=f"hash_{text[:10]}",
                char_count=len(text),
                word_count=len(text.split()),
                status=FeedbackStatus.PENDING,
            )
        )
    await db_session.commit()
    return run


def _make_mock_llm(categories: list[dict]) -> MagicMock:
    """Build a mock LLM that returns a DiscoveryResponse with the given categories."""
    from grainsift.engine.discovery import _DiscoveryResponse, _SuggestedCategory

    response = _DiscoveryResponse(
        categories=[_SuggestedCategory(**c) for c in categories]
    )
    mock = MagicMock()
    mock.complete = AsyncMock(return_value=response)
    return mock


# ─── run_discovery tests ──────────────────────────────────────────────────────


async def test_run_discovery_returns_categories(db_session, run_with_feedback):
    from grainsift.config import Settings

    mock_llm = _make_mock_llm([
        {"key": "app_stability", "label": "App Stability", "description": "Crashes", "examples": ["crashes"]},
        {"key": "billing", "label": "Billing", "description": "Billing issues", "examples": ["charged twice"]},
        {"key": "delivery", "label": "Delivery", "description": "Delivery speed", "examples": ["fast delivery"]},
    ])
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    result = await run_discovery(
        run_id=run_with_feedback.id,
        session=db_session,
        llm=mock_llm,
        settings=settings,
    )

    assert len(result) == 3
    keys = [c.key for c in result]
    assert "app_stability" in keys
    assert "billing" in keys
    assert mock_llm.complete.called


async def test_run_discovery_deduplicates_keys(db_session, run_with_feedback):
    from grainsift.config import Settings

    mock_llm = _make_mock_llm([
        {"key": "app_stability", "label": "App Stability", "description": "x", "examples": []},
        {"key": "app_stability", "label": "Duplicate", "description": "x", "examples": []},
    ])
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    result = await run_discovery(
        run_id=run_with_feedback.id,
        session=db_session,
        llm=mock_llm,
        settings=settings,
    )

    assert len(result) == 1


async def test_run_discovery_filters_other_key(db_session, run_with_feedback):
    from grainsift.config import Settings

    mock_llm = _make_mock_llm([
        {"key": "other", "label": "Other", "description": "miscellaneous", "examples": []},
        {"key": "billing", "label": "Billing", "description": "x", "examples": []},
    ])
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    result = await run_discovery(
        run_id=run_with_feedback.id,
        session=db_session,
        llm=mock_llm,
        settings=settings,
    )

    keys = [c.key for c in result]
    assert "other" not in keys  # 'other' is filtered from suggestions (added automatically on confirm)


async def test_run_discovery_no_feedback_raises(db_session):
    from unittest.mock import MagicMock
    from grainsift.config import Settings

    run = Run(filename="empty.csv", status=RunStatus.PENDING)
    db_session.add(run)
    await db_session.commit()

    # LLM should never be called — error fires before sampling
    mock_llm = MagicMock()
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    with pytest.raises(EnumConfigError, match="no ingested feedback"):
        await run_discovery(
            run_id=run.id,
            session=db_session,
            llm=mock_llm,
            settings=settings,
        )
    mock_llm.complete.assert_not_called()


# ─── save_enum_config tests ───────────────────────────────────────────────────


async def test_save_enum_config_appends_other(db_session, run_with_feedback):
    categories = [
        EnumCategory(key="billing", label="Billing", description="x"),
        EnumCategory(key="app_stability", label="App Stability", description="x"),
    ]
    config = await save_enum_config(
        run_id=run_with_feedback.id,
        categories=categories,
        session=db_session,
    )

    saved_cats = enum_config_to_categories(config)
    keys = [c.key for c in saved_cats]
    assert "other" in keys
    assert keys[-1] == "other"  # other is always last


async def test_save_enum_config_versions_increment(db_session, run_with_feedback):
    cats = [EnumCategory(key="billing", label="Billing", description="x")]

    v1 = await save_enum_config(run_with_feedback.id, cats, db_session)
    v2 = await save_enum_config(run_with_feedback.id, cats, db_session)

    assert v1.version == 1
    assert v2.version == 2


async def test_save_enum_config_empty_raises(db_session, run_with_feedback):
    with pytest.raises(EnumConfigError):
        await save_enum_config(run_with_feedback.id, [], db_session)


async def test_get_latest_enum_config_returns_newest(db_session, run_with_feedback):
    cats = [EnumCategory(key="billing", label="Billing", description="x")]
    await save_enum_config(run_with_feedback.id, cats, db_session)
    await save_enum_config(run_with_feedback.id, cats, db_session)

    latest = await get_latest_enum_config(run_with_feedback.id, db_session)
    assert latest is not None
    assert latest.version == 2


async def test_get_allowed_keys_includes_other(db_session, run_with_feedback):
    cats = [
        EnumCategory(key="billing", label="Billing", description="x"),
        EnumCategory(key="app_stability", label="App Stability", description="x"),
    ]
    config = await save_enum_config(run_with_feedback.id, cats, db_session)
    keys = get_allowed_keys(config)
    assert "billing" in keys
    assert "other" in keys
