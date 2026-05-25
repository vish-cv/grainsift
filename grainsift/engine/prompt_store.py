"""
Prompt store — 3-level lookup: project override → global default → hardcoded fallback.

Global defaults are stored in AppConfig with key prefix "prompt:".
Project overrides are stored in ProjectPrompt rows.
If neither exists, the hardcoded constant from llm/prompts.py is returned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grainsift.llm.prompts import DISCOVERY, EXTRACTION, QUERY_SYSTEM, SUMMARIZATION
from grainsift.models.database import AppConfig, ProjectPrompt


# ─── Hardcoded fallback defaults ──────────────────────────────────────────────

DEFAULTS: dict[str, str] = {
    "discovery_system": DISCOVERY.system,
    "discovery_user":   DISCOVERY.user_template,
    "extraction_system": EXTRACTION.system,
    "extraction_user":  EXTRACTION.user_template,
    "query_system":     QUERY_SYSTEM,
    "summary_system":   SUMMARIZATION.system,
    "summary_user":     SUMMARIZATION.user_template,
}


# ─── Metadata (used by frontend for labels, hints, read-only flag) ────────────

@dataclass(frozen=True)
class PromptMeta:
    label: str
    description: str
    required_vars: list[str]
    read_only: bool = False


PROMPT_META: dict[str, PromptMeta] = {
    "discovery_system": PromptMeta(
        label="Discovery — System",
        description="Sets the AI's role and domain context when discovering categories from your feedback.",
        required_vars=[],
    ),
    "discovery_user": PromptMeta(
        label="Discovery — User Template",
        description="Instructions for how the AI should propose categories. Must contain the required template variables.",
        required_vars=["{n}", "{min_categories}", "{max_categories}", "{locked_section}", "{feedback_json}"],
    ),
    "extraction_system": PromptMeta(
        label="Extraction — System",
        description="Sets the AI's role and domain context when classifying each feedback item.",
        required_vars=[],
    ),
    "extraction_user": PromptMeta(
        label="Extraction — User Template",
        description="Classification instructions and JSON output schema. Read-only — modifying the schema structure breaks extraction.",
        required_vars=["{n}", "{categories_json}", "{items_json}"],
        read_only=True,
    ),
    "query_system": PromptMeta(
        label="Query Engine — System",
        description="Sets the AI's role when answering natural-language questions about your labeled data.",
        required_vars=[],
    ),
    "summary_system": PromptMeta(
        label="Summary — System",
        description="Sets the AI's role when writing the executive summary for a completed run.",
        required_vars=[],
    ),
    "summary_user": PromptMeta(
        label="Summary — User Template",
        description="Template for the summary request. Must contain the required template variables.",
        required_vars=[
            "{filename}", "{date_range}", "{total}", "{volume_summary}",
            "{pct_negative}", "{pct_neutral}", "{pct_positive}",
            "{urgency_summary}", "{accuracy_pct}",
        ],
    ),
}

PROMPT_KEYS = list(DEFAULTS.keys())


# ─── Lookup ───────────────────────────────────────────────────────────────────


async def get_prompt(
    session: AsyncSession,
    key: str,
    project_id: str | None = None,
) -> str:
    """
    Return the prompt content for `key`, applying the 3-level fallback:
    project override → global AppConfig default → hardcoded constant.
    """
    if project_id:
        row = (
            await session.execute(
                select(ProjectPrompt).where(
                    ProjectPrompt.project_id == project_id,
                    ProjectPrompt.key == key,
                )
            )
        ).scalar_one_or_none()
        if row:
            return row.content

    config_row = (
        await session.execute(
            select(AppConfig).where(AppConfig.key == f"prompt:{key}")
        )
    ).scalar_one_or_none()
    if config_row and config_row.value:
        return config_row.value

    return DEFAULTS.get(key, "")


async def get_all_prompts(
    session: AsyncSession,
    project_id: str | None = None,
) -> dict[str, dict]:
    """
    Return all prompts with resolved content and source label.
    Used by the API to populate the prompts editor UI.
    """
    # Load all relevant DB rows in two queries
    global_rows = {
        row.key.removeprefix("prompt:"): row.value
        for row in (
            await session.execute(
                select(AppConfig).where(AppConfig.key.like("prompt:%"))
            )
        ).scalars().all()
        if row.value
    }

    project_rows: dict[str, str] = {}
    if project_id:
        project_rows = {
            row.key: row.content
            for row in (
                await session.execute(
                    select(ProjectPrompt).where(ProjectPrompt.project_id == project_id)
                )
            ).scalars().all()
        }

    result = {}
    for key in PROMPT_KEYS:
        meta = PROMPT_META[key]
        if key in project_rows:
            content = project_rows[key]
            source = "project"
        elif key in global_rows:
            content = global_rows[key]
            source = "global"
        else:
            content = DEFAULTS[key]
            source = "default"

        result[key] = {
            "key": key,
            "label": meta.label,
            "description": meta.description,
            "required_vars": meta.required_vars,
            "read_only": meta.read_only,
            "content": content,
            "source": source,
        }
    return result


# ─── Save helpers (used by API routes) ───────────────────────────────────────


async def set_global_prompt(session: AsyncSession, key: str, content: str) -> None:
    row = (
        await session.execute(
            select(AppConfig).where(AppConfig.key == f"prompt:{key}")
        )
    ).scalar_one_or_none()
    if row:
        row.value = content
    else:
        session.add(AppConfig(key=f"prompt:{key}", value=content))
    await session.commit()


async def reset_global_prompt(session: AsyncSession, key: str) -> None:
    row = (
        await session.execute(
            select(AppConfig).where(AppConfig.key == f"prompt:{key}")
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()


async def set_project_prompt(
    session: AsyncSession, project_id: str, key: str, content: str
) -> None:
    from datetime import UTC, datetime

    row = (
        await session.execute(
            select(ProjectPrompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.key == key,
            )
        )
    ).scalar_one_or_none()
    if row:
        row.content = content
        row.updated_at = datetime.now(UTC)
    else:
        session.add(ProjectPrompt(project_id=project_id, key=key, content=content))
    await session.commit()


async def reset_project_prompt(
    session: AsyncSession, project_id: str, key: str
) -> None:
    row = (
        await session.execute(
            select(ProjectPrompt).where(
                ProjectPrompt.project_id == project_id,
                ProjectPrompt.key == key,
            )
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()
