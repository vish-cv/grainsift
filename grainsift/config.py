from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    anthropic_model: str = "claude-sonnet-4-6"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.0-flash"
    ollama_model: str = "llama3.2"

    # Database — defaults to ~/.grainsift/grainsift.db
    database_url: str = Field(default="")

    # Processing
    batch_size: int = Field(default=5, ge=1, le=10)
    confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    max_feedback_words: int = Field(default=400, ge=50)
    chunk_overlap_words: int = 50
    min_feedback_words: int = 3

    # Server
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False

    @model_validator(mode="after")
    def set_defaults(self) -> "Settings":
        if not self.database_url:
            data_dir = Path.home() / ".grainsift"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite+aiosqlite:///{data_dir}/grainsift.db"
        return self

    @property
    def data_dir(self) -> Path:
        return Path.home() / ".grainsift"

    @property
    def active_model(self) -> str:
        match self.llm_provider:
            case LLMProvider.ANTHROPIC:
                return self.anthropic_model
            case LLMProvider.OPENAI:
                return self.openai_model
            case LLMProvider.GEMINI:
                return self.gemini_model
            case LLMProvider.OLLAMA:
                return self.ollama_model

    def require_api_key(self) -> str:
        """Return the configured API key or raise ConfigError."""
        from grainsift.exceptions import ConfigError

        match self.llm_provider:
            case LLMProvider.ANTHROPIC:
                if not self.anthropic_api_key:
                    raise ConfigError(
                        "ANTHROPIC_API_KEY is not set. Add it to your .env file."
                    )
                return self.anthropic_api_key
            case LLMProvider.OPENAI:
                if not self.openai_api_key:
                    raise ConfigError(
                        "OPENAI_API_KEY is not set. Add it to your .env file."
                    )
                return self.openai_api_key
            case LLMProvider.GEMINI:
                if not self.gemini_api_key:
                    raise ConfigError(
                        "GEMINI_API_KEY is not set. Add it to your .env file."
                    )
                return self.gemini_api_key
            case LLMProvider.OLLAMA:
                return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
