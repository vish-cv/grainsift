"""Extraction API routes (Stage 4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from grainsift.api.deps import AppSettings, DbSession, LLMClient
from grainsift.engine.extraction import estimate_extraction_cost, run_extraction
from grainsift.exceptions import EnumConfigError
from grainsift.models.database import Run
from grainsift.models.enums import RunStatus
from grainsift.models.schemas import CostEstimate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs/{run_id}", tags=["extraction"])


@router.get("/estimate", response_model=CostEstimate)
async def get_cost_estimate(
    run_id: str,
    db: DbSession,
    settings: AppSettings,
    llm: LLMClient,
) -> CostEstimate:
    """Return a cost/time estimate before extraction."""
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM client not configured")

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return await estimate_extraction_cost(
        run_id=run_id,
        session=db,
        llm=llm,
        settings=settings,
    )


@router.post("/extract")
async def extract(
    run_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    llm: LLMClient,
) -> dict:
    """
    Start extraction in the background and return immediately.
    Poll GET /runs/{run_id} for live status (processed_rows, flagged_rows, status).
    """
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM client not configured")

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status not in (RunStatus.PENDING,):
        raise HTTPException(
            status_code=409,
            detail=f"Run is in '{run.status}' state — can only extract from a pending run",
        )

    run.status = RunStatus.EXTRACTING
    await db.commit()

    session_factory = request.app.state.session_factory

    background_tasks.add_task(
        _run_extraction_bg,
        run_id=run_id,
        session_factory=session_factory,
        llm=llm,
        settings=settings,
    )

    return {"status": "started", "run_id": run_id}


async def _run_extraction_bg(run_id: str, session_factory, llm, settings) -> None:
    """Background task: runs extraction with its own DB session."""
    async with session_factory() as session:
        try:
            await run_extraction(run_id, session, llm, settings)
        except Exception as exc:
            logger.exception("Background extraction failed for run %s: %s", run_id, exc)
            # Open a fresh session to mark run as failed
            async with session_factory() as err_session:
                run = await err_session.get(Run, run_id)
                if run and run.status == RunStatus.EXTRACTING:
                    run.status = RunStatus.FAILED
                    await err_session.commit()
