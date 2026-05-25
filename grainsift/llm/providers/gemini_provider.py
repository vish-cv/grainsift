"""
Gemini provider via Google's OpenAI-compatible REST endpoint.
No extra SDK required — uses the openai package pointed at the Gemini base URL.
Docs: https://ai.google.dev/gemini-api/docs/openai
"""

from __future__ import annotations

from typing import TypeVar

import instructor
from instructor.core import InstructorRetryException
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from pydantic import BaseModel

from grainsift.exceptions import LLMError, LLMRateLimitError, LLMValidationError
from grainsift.llm.providers.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Approximate USD per million tokens (Google pricing, 2025)
_COSTS: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-flash-lite": (0.0375, 0.15),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
    "default": (0.075, 0.30),
}


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._model = model
        raw_client = AsyncOpenAI(api_key=api_key, base_url=_GEMINI_BASE_URL)
        # Gemini's OpenAI-compatible endpoint rejects complex tool-call schemas.
        # JSON mode injects the schema into the prompt instead of using function calling.
        self._client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "gemini"

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
            return await self._client.chat.completions.create(  # type: ignore[return-value]
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                response_model=response_model,
                max_retries=max_retries,
            )
        except InstructorRetryException as e:
            raise LLMValidationError(
                f"Schema validation failed after {max_retries} retries: {e}"
            ) from e
        except RateLimitError as e:
            raise LLMRateLimitError("Gemini rate limit exceeded") from e
        except APIStatusError as e:
            raise LLMError(f"Gemini API error {e.status_code}: {e.message}") from e
