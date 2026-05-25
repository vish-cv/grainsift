"""All GrainSift-specific exceptions."""


class GrainSiftError(Exception):
    """Base exception for all GrainSift errors."""


class ConfigError(GrainSiftError):
    """Invalid or missing configuration."""


class IngestError(GrainSiftError):
    """Error during CSV ingestion."""


class LLMError(GrainSiftError):
    """Error from an LLM provider."""


class LLMRateLimitError(LLMError):
    """Provider rate limit hit."""


class LLMValidationError(LLMError):
    """LLM response failed schema validation after all retries."""


class RunNotFoundError(GrainSiftError):
    """Requested run does not exist."""


class EnumConfigError(GrainSiftError):
    """Invalid or missing enum configuration."""
