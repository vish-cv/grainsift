"""LLM client factory. Returns the correct provider based on config."""

from __future__ import annotations

from functools import lru_cache

from grainsift.config import LLMProvider, Settings
from grainsift.llm.providers.anthropic_provider import AnthropicProvider
from grainsift.llm.providers.base import BaseLLMProvider
from grainsift.llm.providers.gemini_provider import GeminiProvider
from grainsift.llm.providers.ollama_provider import OllamaProvider
from grainsift.llm.providers.openai_provider import OpenAIProvider


def create_llm_client(settings: Settings) -> BaseLLMProvider:
    """
    Instantiate the LLM provider configured in settings.
    Validates that the required API key is present before constructing.
    """
    api_key = settings.require_api_key()

    match settings.llm_provider:
        case LLMProvider.ANTHROPIC:
            return AnthropicProvider(api_key=api_key, model=settings.anthropic_model)
        case LLMProvider.OPENAI:
            return OpenAIProvider(api_key=api_key, model=settings.openai_model)
        case LLMProvider.GEMINI:
            return GeminiProvider(api_key=api_key, model=settings.gemini_model)
        case LLMProvider.OLLAMA:
            return OllamaProvider(
                model=settings.ollama_model,
                base_url=f"{settings.ollama_base_url}/v1",
            )


@lru_cache(maxsize=1)
def get_llm_client(settings: Settings) -> BaseLLMProvider:
    """Cached singleton — safe because settings are immutable after startup."""
    return create_llm_client(settings)
