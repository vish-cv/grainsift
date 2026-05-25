from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """
    All LLM providers expose a single async `complete` method that returns
    a validated Pydantic model. Instructor handles retries and schema enforcement.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        max_retries: int = 2,
        **kwargs: object,
    ) -> T:
        """Send messages and return a validated response_model instance."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier string sent to the provider."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'anthropic'."""

    @abstractmethod
    def cost_per_million_tokens(self) -> tuple[float, float]:
        """Return (input_cost, output_cost) in USD per million tokens."""

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_rate, output_rate = self.cost_per_million_tokens()
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
