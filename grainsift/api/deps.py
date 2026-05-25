"""FastAPI dependency injectors."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.config import Settings, get_settings
from grainsift.llm.providers.base import BaseLLMProvider


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session scoped to the request."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_settings_dep() -> Settings:
    return get_settings()


async def get_llm(request: Request, db: AsyncSession = Depends(get_db)) -> BaseLLMProvider | None:
    """Return the active LLM client — prefer DB config, fall back to startup state."""
    from grainsift.engine.config_store import build_llm_provider, load_llm_config

    cfg = await load_llm_config(db)
    if cfg.is_configured:
        client = build_llm_provider(cfg)
        if client:
            return client
    return request.app.state.llm_client  # type: ignore[no-any-return]


# Annotated shorthands for cleaner route signatures
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
LLMClient = Annotated[BaseLLMProvider, Depends(get_llm)]
