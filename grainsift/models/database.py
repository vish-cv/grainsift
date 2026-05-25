from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    taxonomy_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    runs: Mapped[list["Run"]] = relationship(back_populates="project")

    __table_args__ = (Index("ix_projects_name", "name"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    flagged_rows: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    enum_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="runs")
    feedback: Mapped[list[RawFeedback]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    enum_configs: Mapped[list[EnumConfig]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_runs_status", "status"),
        Index("ix_runs_project_id", "project_id"),
    )


class RawFeedback(Base):
    __tablename__ = "raw_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feedback_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[Run] = relationship(back_populates="feedback")
    label: Mapped[Label | None] = relationship(
        back_populates="feedback",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_raw_feedback_run_id", "run_id"),
        Index("ix_raw_feedback_status", "status"),
        Index("ix_raw_feedback_content_hash", "content_hash"),
    )


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    feedback_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_feedback.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(20), nullable=False)
    urgency: Mapped[str] = mapped_column(String(20), nullable=False)
    key_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    llm_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_flags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    feedback: Mapped[RawFeedback] = relationship(back_populates="label")
    correction: Mapped[Correction | None] = relationship(
        back_populates="label",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_labels_feedback_id", "feedback_id"),
        Index("ix_labels_category", "category"),
        Index("ix_labels_sentiment", "sentiment"),
        Index("ix_labels_urgency", "urgency"),
        Index("ix_labels_source", "source"),
    )


class EnumConfig(Base):
    __tablename__ = "enum_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    categories: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_by: Mapped[str] = mapped_column(String(20), default="discovery")

    run: Mapped[Run] = relationship(back_populates="enum_configs")

    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_enum_config_run_version"),
        Index("ix_enum_configs_run_id", "run_id"),
    )


class AppConfig(Base):
    """Single-row key-value store for application settings (LLM, thresholds, etc.)."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("labels.id", ondelete="CASCADE"), nullable=False
    )
    original_category: Mapped[str] = mapped_column(String(100), nullable=False)
    corrected_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    original_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    corrected_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    original_urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    corrected_urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    label: Mapped[Label] = relationship(back_populates="correction")

    __table_args__ = (Index("ix_corrections_label_id", "label_id"),)


class QueryMessage(Base):
    """One row per Q&A exchange within a query session."""

    __tablename__ = "query_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    key_insights: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    sources: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_query_messages_run_id", "run_id"),
        Index("ix_query_messages_session_id", "session_id"),
    )


class ProjectPrompt(Base):
    """Project-level prompt overrides. project_id=NULL is not used here — global defaults live in AppConfig."""

    __tablename__ = "project_prompts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_project_prompts_project_key"),
    )


class CalibrationResult(Base):
    """One row per run — upserted each time calibration is run."""

    __tablename__ = "calibration_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sample_size: Mapped[int] = mapped_column(Integer)
    category_agreement: Mapped[float] = mapped_column(Float)
    sentiment_agreement: Mapped[float] = mapped_column(Float)
    urgency_agreement: Mapped[float] = mapped_column(Float)
    per_category_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_calibration_results_run_id", "run_id"),)


def configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64 MB
        cursor.close()
