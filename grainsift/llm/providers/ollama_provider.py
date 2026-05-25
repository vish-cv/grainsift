"""
Ollama provider for fully local inference.
Uses the OpenAI-compatible endpoint that Ollama exposes on localhost.
"""

from __future__ import annotations

from typing import TypeVar

import instructor
from instructor.core import InstructorRetryException
from openai import AsyncOpenAI, APIStatusError
from pydantic import BaseModel

from grainsift.exceptions import LLMError, LLMValidationError
from grainsift.llm.providers.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434/v1",
    ) -> None:
        self._model = model
        raw_client = AsyncOpenAI(api_key="ollama", base_url=base_url)
        self._client = instructor.from_openai(raw_client)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "ollama"

    def cost_per_million_tokens(self) -> tuple[float, float]:
        return (0.0, 0.0)

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
        except APIStatusError as e:
            raise LLMError(
                f"Ollama API error {e.status_code}: {e.message}. "
                "Is Ollama running? Try: ollama serve"
            ) from e
