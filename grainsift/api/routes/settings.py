"""Settings routes — LLM provider, API key, model, thresholds."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from grainsift.api.deps import DbSession
from grainsift.engine.config_store import LLMConfig, build_llm_provider, load_llm_config, save_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-4o", "gpt-4o-mini", "o1", "o1-mini"],
    "gemini": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"],
    "ollama": [],  # free-text — user types the model name
}


class SettingsResponse(BaseModel):
    provider: str
    model: str
    api_key_set: bool
    api_key_preview: str  # last 4 chars, e.g. "...a3f2"
    ollama_base_url: str
    batch_size: int
    confidence_threshold: float
    is_configured: bool


class SettingsUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None       # omit or send "" to leave unchanged
    ollama_base_url: str | None = None
    batch_size: int | None = None
    confidence_threshold: float | None = None


class TestResult(BaseModel):
    ok: bool
    message: str


def _mask_key(key: str) -> str:
    if not key:
        return ""
    return f"...{key[-4:]}" if len(key) >= 4 else "****"


def _cfg_to_response(cfg: LLMConfig) -> SettingsResponse:
    return SettingsResponse(
        provider=cfg.provider,
        model=cfg.model,
        api_key_set=bool(cfg.api_key),
        api_key_preview=_mask_key(cfg.api_key),
        ollama_base_url=cfg.ollama_base_url,
        batch_size=cfg.batch_size,
        confidence_threshold=cfg.confidence_threshold,
        is_configured=cfg.is_configured,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(db: DbSession) -> SettingsResponse:
    cfg = await load_llm_config(db)
    return _cfg_to_response(cfg)


@router.get("/models")
async def get_models() -> dict[str, list[str]]:
    return _MODELS


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    db: DbSession,
) -> SettingsResponse:
    cfg = await load_llm_config(db)

    updates: dict[str, str] = {}
    if body.provider is not None:
        updates["llm_provider"] = body.provider
    if body.model is not None:
        updates["llm_model"] = body.model
    if body.api_key:  # only update if non-empty — empty means "leave as is"
        updates["llm_api_key"] = body.api_key
    if body.ollama_base_url is not None:
        updates["ollama_base_url"] = body.ollama_base_url
    if body.batch_size is not None:
        updates["batch_size"] = str(body.batch_size)
    if body.confidence_threshold is not None:
        updates["confidence_threshold"] = str(body.confidence_threshold)

    if updates:
        await save_llm_config(db, updates)
        cfg = await load_llm_config(db)

    # Rebuild the live LLM client in app state
    new_client = build_llm_provider(cfg)
    request.app.state.llm_client = new_client
    if new_client:
        logger.info("LLM client updated: %s / %s", cfg.provider, cfg.model)

    return _cfg_to_response(cfg)


@router.post("/test", response_model=TestResult)
async def test_connection(db: DbSession) -> TestResult:
    """Send a minimal completion to verify the API key and model work."""
    from pydantic import BaseModel as PydanticBase

    cfg = await load_llm_config(db)
    if not cfg.is_configured:
        return TestResult(ok=False, message="No LLM configured. Save your settings first.")

    provider = build_llm_provider(cfg)
    if provider is None:
        return TestResult(ok=False, message="Could not create LLM client.")

    class _Ping(PydanticBase):
        ok: bool

    try:
        result = await provider.complete(
            messages=[{"role": "user", "content": 'Reply with JSON: {"ok": true}'}],
            response_model=_Ping,
            max_retries=1,
        )
        if result.ok:
            return TestResult(ok=True, message=f"Connected to {cfg.provider} / {cfg.model}")
        return TestResult(ok=False, message="Unexpected response from LLM.")
    except Exception as exc:
        return TestResult(ok=False, message=str(exc))
