"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from grainsift.api.main import create_app
from grainsift.models.database import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def sample_csv_path() -> Path:
    return FIXTURES_DIR / "sample_feedback.csv"


@pytest.fixture(scope="session")
def sample_csv_bytes(sample_csv_path: Path) -> bytes:
    return sample_csv_path.read_bytes()


@pytest.fixture
async def engine():
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(engine):
    """HTTP test client wired to an in-memory database."""
    app = create_app()

    # Override the engine the app creates during lifespan
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.llm_client = None  # LLM not needed for ingest tests

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
