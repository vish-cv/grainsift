from __future__ import annotations

from typing import TypeVar

import instructor
from instructor.core import InstructorRetryException
from anthropic import AsyncAnthropic, APIStatusError, RateLimitError
from pydantic import BaseModel

from grainsift.exceptions import LLMError, LLMRateLimitError, LLMValidationError
from grainsift.llm.providers.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)

# Approximate USD per million tokens (Anthropic pricing, 2025)
_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
    # fallback for unknown models
    "default": (3.0, 15.0),
}


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._model = model
        raw_client = AsyncAnthropic(api_key=api_key)
        self._client = instructor.from_anthropic(raw_client)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def cost_per_million_tokens(self) -> tuple[float, float]:
        return _COSTS.get(self._model, _COSTS["default"])

    async def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        max_retries: int = 2,
        **kwargs: object,
    ) -> T:
        try:
            return await self._client.messages.create(  # type: ignore[return-value]
                model=self._model,
                max_tokens=kwargs.get("max_tokens", 4096),  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                response_model=response_model,
                max_retries=max_retries,
            )
        except InstructorRetryException as e:
            raise LLMValidationError(
                f"Schema validation failed after {max_retries} retries: {e}"
            ) from e
        except RateLimitError as e:
            raise LLMRateLimitError("Anthropic rate limit exceeded") from e
        except APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
