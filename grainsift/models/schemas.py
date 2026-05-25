"""Pydantic v2 schemas for API request/response. Separate from ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from grainsift.models.enums import (
    EnumConfigSource,
    FeedbackStatus,
    LabelSource,
    ReviewFlag,
    RunStatus,
    Sentiment,
    Urgency,
)


# ─── Shared ───────────────────────────────────────────────────────────────────


class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Column Mapping ───────────────────────────────────────────────────────────


class ColumnMapping(BaseModel):
    feedback_column: str
    date_column: str | None = None
    source_column: str | None = None

    @field_validator("feedback_column")
    @classmethod
    def feedback_column_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("feedback_column cannot be empty")
        return v.strip()


# ─── Run ──────────────────────────────────────────────────────────────────────


class RunCreate(BaseModel):
    filename: str


class RunResponse(OrmBase):
    id: str
    project_id: str | None
    filename: str
    total_rows: int
    processed_rows: int
    flagged_rows: int
    skipped_rows: int
    duplicate_rows: int
    enum_version: int | None
    model_used: str | None
    estimated_cost: float | None
    actual_cost: float | None
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None
    summary: str | None
    ai_summary: str | None = None


class RunListResponse(BaseModel):
    runs: list[RunResponse]
    total: int


# ─── Ingest ───────────────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    column_mapping: ColumnMapping


class IngestResult(BaseModel):
    run_id: str
    total_rows: int
    accepted_rows: int
    duplicate_rows: int
    skipped_rows: int
    pii_redactions: int
    pii_types: dict[str, int] = Field(default_factory=dict)
    non_english_rows: int = 0
    language_distribution: dict[str, int] = Field(default_factory=dict)
    column_warnings: list[str] = Field(default_factory=list)


class UploadPreview(BaseModel):
    """First 5 rows and detected column names, returned before ingest."""

    columns: list[str]
    preview_rows: list[dict[str, Any]]
    row_count_estimate: int


# ─── Raw Feedback ─────────────────────────────────────────────────────────────


class RawFeedbackResponse(OrmBase):
    id: str
    run_id: str
    original_text: str
    clean_text: str | None
    language: str | None
    language_confidence: float | None
    source_channel: str | None
    feedback_date: datetime | None
    char_count: int
    word_count: int
    chunk_index: int
    total_chunks: int
    status: FeedbackStatus
    created_at: datetime


# ─── Label ────────────────────────────────────────────────────────────────────


class LabelResponse(OrmBase):
    id: str
    feedback_id: str
    category: str
    sentiment: Sentiment
    urgency: Urgency
    key_phrase: str | None
    confidence: float
    source: LabelSource
    llm_category: str | None
    review_flags: list[ReviewFlag] | None
    created_at: datetime
    reviewed_at: datetime | None


# ─── Enum Config ──────────────────────────────────────────────────────────────


class EnumCategory(BaseModel):
    key: str
    label: str
    description: str = ""
    examples: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def key_is_snake_case(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError(
                f"Category key '{v}' must be snake_case (lowercase, underscores only)"
            )
        return v


class EnumConfigCreate(BaseModel):
    run_id: str | None = None  # optional — path param takes precedence
    categories: list[EnumCategory]
    created_by: EnumConfigSource = EnumConfigSource.DISCOVERY


class EnumConfigResponse(OrmBase):
    id: str
    run_id: str
    version: int
    categories: dict[str, Any]
    created_at: datetime
    created_by: str


# ─── Review Queue ─────────────────────────────────────────────────────────────


class ReviewItem(OrmBase):
    feedback_id: str
    original_text: str
    label_id: str
    suggested_category: str
    suggested_sentiment: Sentiment
    suggested_urgency: Urgency
    confidence: float
    review_flags: list[ReviewFlag]


class ReviewDecision(BaseModel):
    label_id: str
    action: str  # confirm | edit | skip
    corrected_category: str | None = None
    corrected_sentiment: Sentiment | None = None
    corrected_urgency: Urgency | None = None
    reviewer_notes: str | None = None


# ─── Dashboard ────────────────────────────────────────────────────────────────


class CategoryCount(BaseModel):
    category: str
    count: int


class SentimentBreakdown(BaseModel):
    category: str
    positive: int
    negative: int
    neutral: int
    mixed: int


class UrgencyCount(BaseModel):
    urgency: Urgency
    count: int


class DashboardStats(BaseModel):
    run_id: str
    total_labeled: int
    human_reviewed: int
    auto_labeled: int
    volume_by_category: list[CategoryCount]
    sentiment_by_category: list[SentimentBreakdown]
    urgency_distribution: list[UrgencyCount]
    other_volume: int
    other_pct: float


# ─── LLM / Cost Estimate ──────────────────────────────────────────────────────


class CostEstimate(BaseModel):
    provider: str
    model: str
    estimated_items: int
    estimated_api_calls: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    estimated_minutes: float
