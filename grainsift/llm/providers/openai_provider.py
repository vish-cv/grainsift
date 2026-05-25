from __future__ import annotations

from typing import TypeVar

import instructor
from instructor.core import InstructorRetryException
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from pydantic import BaseModel

from grainsift.exceptions import LLMError, LLMRateLimitError, LLMValidationError
from grainsift.llm.providers.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)

# Approximate USD per million tokens (OpenAI pricing, 2025)
_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "o1": (15.0, 60.0),
    "o1-mini": (3.0, 12.0),
    "default": (2.50, 10.0),
}


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._model = model
        raw_client = AsyncOpenAI(api_key=api_key)
        self._client = instructor.from_openai(raw_client)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"

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
            raise LLMRateLimitError("OpenAI rate limit exceeded") from e
        except APIStatusError as e:
            raise LLMError(f"OpenAI API error {e.status_code}: {e.message}") from e
