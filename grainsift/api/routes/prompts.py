"""Prompt management routes — view and override LLM prompts globally or per project."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grainsift.api.deps import DbSession
from grainsift.engine.prompt_store import (
    PROMPT_KEYS,
    get_all_prompts,
    reset_global_prompt,
    reset_project_prompt,
    set_global_prompt,
    set_project_prompt,
)
from grainsift.models.database import Project

router = APIRouter(tags=["prompts"])


class PromptItem(BaseModel):
    key: str
    label: str
    description: str
    required_vars: list[str]
    read_only: bool
    content: str
    source: str  # "default" | "global" | "project"


class PromptUpdate(BaseModel):
    content: str = Field(min_length=1)


# ─── Global defaults ──────────────────────────────────────────────────────────


@router.get("/prompts", response_model=dict[str, PromptItem])
async def list_global_prompts(db: DbSession) -> dict[str, PromptItem]:
    """All prompts resolved against global defaults (no project overrides)."""
    data = await get_all_prompts(db, project_id=None)
    return {k: PromptItem(**v) for k, v in data.items()}


@router.put("/prompts/{key}", response_model=PromptItem)
async def update_global_prompt(key: str, body: PromptUpdate, db: DbSession) -> PromptItem:
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    from grainsift.engine.prompt_store import PROMPT_META
    if PROMPT_META[key].read_only:
        raise HTTPException(status_code=400, detail=f"Prompt '{key}' is read-only.")
    await set_global_prompt(db, key, body.content)
    data = await get_all_prompts(db, project_id=None)
    return PromptItem(**data[key])


@router.delete("/prompts/{key}", status_code=204)
async def reset_global_prompt_to_default(key: str, db: DbSession) -> None:
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    await reset_global_prompt(db, key)


# ─── Project overrides ────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/prompts", response_model=dict[str, PromptItem])
async def list_project_prompts(project_id: str, db: DbSession) -> dict[str, PromptItem]:
    """All prompts for a project: project override → global default → hardcoded."""
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    data = await get_all_prompts(db, project_id=project_id)
    return {k: PromptItem(**v) for k, v in data.items()}


@router.put("/projects/{project_id}/prompts/{key}", response_model=PromptItem)
async def update_project_prompt(
    project_id: str, key: str, body: PromptUpdate, db: DbSession
) -> PromptItem:
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    from grainsift.engine.prompt_store import PROMPT_META
    if PROMPT_META[key].read_only:
        raise HTTPException(status_code=400, detail=f"Prompt '{key}' is read-only.")
    await set_project_prompt(db, project_id, key, body.content)
    data = await get_all_prompts(db, project_id=project_id)
    return PromptItem(**data[key])


@router.delete("/projects/{project_id}/prompts/{key}", status_code=204)
async def reset_project_prompt_to_global(
    project_id: str, key: str, db: DbSession
) -> None:
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if key not in PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    await reset_project_prompt(db, project_id, key)
