"""Discovery API routes (Stage 3)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from grainsift.api.deps import AppSettings, DbSession, LLMClient
from grainsift.engine.discovery import (
    TaxonomySource,
    enum_config_to_categories,
    get_latest_enum_config,
    import_taxonomy_from_run,
    list_runs_with_taxonomy,
    run_discovery,
    save_enum_config,
)
from grainsift.exceptions import EnumConfigError, LLMError
from grainsift.models.database import Label, Project, RawFeedback, Run
from grainsift.models.enums import EnumConfigSource, FeedbackStatus, ReviewFlag, RunStatus
from grainsift.models.schemas import (
    EnumCategory,
    EnumConfigCreate,
    EnumConfigResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs/{run_id}/discovery", tags=["discovery"])


class StartDiscoveryBody(BaseModel):
    locked_categories: list[EnumCategory] = Field(default_factory=list)


@router.post("/start", response_model=list[EnumCategory])
async def start_discovery(
    run_id: str,
    db: DbSession,
    settings: AppSettings,
    llm: LLMClient,
    sample_size: int = 250,
    body: StartDiscoveryBody | None = Body(default=None),
) -> list[EnumCategory]:
    """
    Sample the run's feedback and return LLM-suggested categories.
    Pass `locked_categories` in the body to pin specific categories and only
    fill gaps around them. Does NOT persist anything.
    """
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="LLM client not configured. Add your API key to .env and restart.",
        )

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    run.status = RunStatus.DISCOVERING
    await db.commit()

    try:
        suggestions = await run_discovery(
            run_id=run_id,
            session=db,
            llm=llm,
            settings=settings,
            sample_size=sample_size,
            locked_categories=body.locked_categories if body else [],
        )
    except EnumConfigError as exc:
        run.status = RunStatus.PENDING
        await db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        run.status = RunStatus.FAILED
        await db.commit()
        logger.exception("LLM error during discovery for run %s", run_id)
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    run.status = RunStatus.PENDING
    await db.commit()

    return suggestions


@router.get("/available-taxonomies", response_model=list[TaxonomySource])
async def get_available_taxonomies(run_id: str, db: DbSession) -> list[TaxonomySource]:
    """Return other runs that have a saved taxonomy, for the import picker."""
    return await list_runs_with_taxonomy(run_id, db)


@router.post("/import/{source_run_id}", response_model=list[EnumCategory])
async def import_taxonomy(
    run_id: str,
    source_run_id: str,
    db: DbSession,
) -> list[EnumCategory]:
    """
    Return the categories from another run's latest taxonomy without persisting.
    The frontend displays them in the edit phase; the user calls /confirm to save.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    try:
        return await import_taxonomy_from_run(run_id, source_run_id, db)
    except EnumConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/confirm", response_model=EnumConfigResponse, status_code=201)
async def confirm_discovery(
    run_id: str,
    body: EnumConfigCreate,
    db: DbSession,
) -> EnumConfigResponse:
    """
    Save the user's confirmed (possibly edited) category list.
    This locks in the taxonomy before extraction runs.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if not body.categories:
        raise HTTPException(status_code=422, detail="At least one category is required")

    try:
        config = await save_enum_config(
            run_id=run_id,
            categories=body.categories,
            session=db,
            created_by=body.created_by,
        )
    except EnumConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Re-flag any labels whose category is no longer in the new taxonomy
    valid_keys: set[str] = set(config.categories.keys())
    orphan_rows = (
        await db.execute(
            select(Label, RawFeedback)
            .join(RawFeedback, Label.feedback_id == RawFeedback.id)
            .where(
                RawFeedback.run_id == run_id,
                Label.reviewed_at.is_(None),
            )
        )
    ).all()
    for row in orphan_rows:
        label, feedback = row.Label, row.RawFeedback
        if label.category not in valid_keys:
            flags: list[str] = list(label.review_flags or [])
            if ReviewFlag.CATEGORY_ORPHANED not in flags:
                flags.append(ReviewFlag.CATEGORY_ORPHANED)
            label.review_flags = flags
            feedback.status = FeedbackStatus.FLAGGED
    await db.commit()

    # If this run belongs to a project that has no taxonomy yet, mark it as the source
    if run.project_id:
        project = await db.get(Project, run.project_id)
        if project and not project.taxonomy_run_id:
            project.taxonomy_run_id = run_id
            await db.commit()
            logger.info("Set taxonomy_run_id=%s for project %s", run_id, run.project_id)

    return EnumConfigResponse.model_validate(config)


@router.post("/use-project-taxonomy", response_model=list[EnumCategory])
async def use_project_taxonomy(run_id: str, db: DbSession) -> list[EnumCategory]:
    """
    Load the project's established taxonomy for this run without an LLM call.
    Returns empty list if the run has no project or the project has no taxonomy yet.
    """
    run = await db.get(Run, run_id)
    if not run or not run.project_id:
        raise HTTPException(status_code=400, detail="Run does not belong to a project.")
    project = await db.get(Project, run.project_id)
    if not project or not project.taxonomy_run_id:
        raise HTTPException(status_code=404, detail="Project has no established taxonomy yet.")
    try:
        return await import_taxonomy_from_run(run_id, project.taxonomy_run_id, db)
    except EnumConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/config", response_model=EnumConfigResponse)
async def get_enum_config(run_id: str, db: DbSession) -> EnumConfigResponse:
    """Return the latest confirmed enum config for this run."""
    config = await get_latest_enum_config(run_id, db)
    if not config:
        raise HTTPException(
            status_code=404, detail=f"No enum config found for run {run_id}"
        )
    return EnumConfigResponse.model_validate(config)


@router.get("/config/categories", response_model=list[EnumCategory])
async def get_enum_categories(run_id: str, db: DbSession) -> list[EnumCategory]:
    """Return the category list from the latest enum config."""
    config = await get_latest_enum_config(run_id, db)
    if not config:
        raise HTTPException(status_code=404, detail="No enum config found")
    return enum_config_to_categories(config)
