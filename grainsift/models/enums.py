from enum import StrEnum


class FeedbackStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FLAGGED = "flagged"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class Urgency(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LabelSource(StrEnum):
    LLM = "llm"
    HUMAN = "human"


class RunStatus(StrEnum):
    PENDING = "pending"
    INGESTING = "ingesting"
    DISCOVERING = "discovering"
    EXTRACTING = "extracting"
    COMPLETE = "complete"
    FAILED = "failed"


class ReviewFlag(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    CATEGORY_OTHER = "category_other"
    SHORT_TEXT = "short_text"
    SCHEMA_RETRY = "schema_retry"
    LANGUAGE_FLAG = "language_flag"
    RANDOM_SAMPLE = "random_sample"
    HIGH_URGENCY_LOW_CONFIDENCE = "high_urgency_low_confidence"
    CATEGORY_ORPHANED = "category_orphaned"


class EnumConfigSource(StrEnum):
    DISCOVERY = "discovery"
    MANUAL = "manual"
    IMPORTED = "imported"
