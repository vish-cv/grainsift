"""Read/write application config from the DB's app_config table."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.models.database import AppConfig

_KEYS = {
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "ollama_base_url",
    "batch_size",
    "confidence_threshold",
}

_DEFAULTS: dict[str, str] = {
    "ollama_base_url": "http://localhost:11434/v1",
    "batch_size": "5",
    "confidence_threshold": "0.7",
}


@dataclass
class LLMConfig:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"
    batch_size: int = 5
    confidence_threshold: float = 0.7

    @property
    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.provider and self.model)
        return bool(self.provider and self.model and self.api_key)


async def load_llm_config(db: AsyncSession) -> LLMConfig:
    rows = (await db.execute(select(AppConfig))).scalars().all()
    kv = {r.key: r.value for r in rows if r.value is not None}

    # fall back to defaults for missing keys
    for k, v in _DEFAULTS.items():
        kv.setdefault(k, v)

    return LLMConfig(
        provider=kv.get("llm_provider", ""),
        model=kv.get("llm_model", ""),
        api_key=kv.get("llm_api_key", ""),
        ollama_base_url=kv.get("ollama_base_url", "http://localhost:11434/v1"),
        batch_size=int(kv.get("batch_size", "5")),
        confidence_threshold=float(kv.get("confidence_threshold", "0.7")),
    )


async def save_llm_config(db: AsyncSession, updates: dict[str, str]) -> None:
    for key, value in updates.items():
        if key not in _KEYS:
            continue
        existing = await db.get(AppConfig, key)
        if existing:
            existing.value = value
        else:
            db.add(AppConfig(key=key, value=value))
    await db.commit()


def build_llm_provider(cfg: LLMConfig):  # type: ignore[return]
    """Instantiate the correct provider from a LLMConfig. Returns None if not configured."""
    from grainsift.llm.providers.anthropic_provider import AnthropicProvider
    from grainsift.llm.providers.gemini_provider import GeminiProvider
    from grainsift.llm.providers.ollama_provider import OllamaProvider
    from grainsift.llm.providers.openai_provider import OpenAIProvider

    if not cfg.is_configured:
        return None

    if cfg.provider == "anthropic":
        return AnthropicProvider(api_key=cfg.api_key, model=cfg.model)
    if cfg.provider == "openai":
        return OpenAIProvider(api_key=cfg.api_key, model=cfg.model)
    if cfg.provider == "gemini":
        return GeminiProvider(api_key=cfg.api_key, model=cfg.model)
    if cfg.provider == "ollama":
        return OllamaProvider(model=cfg.model, base_url=cfg.ollama_base_url)
    return None
