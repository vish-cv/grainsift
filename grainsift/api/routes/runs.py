"""Run management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from grainsift.api.deps import DbSession, LLMClient
from grainsift.exceptions import LLMError
from grainsift.models.database import Run
from grainsift.models.enums import RunStatus
from grainsift.models.schemas import RunCreate, RunListResponse, RunResponse

router = APIRouter(prefix="/runs", tags=["runs"])


class SummaryResponse(BaseModel):
    run_id: str
    summary: str


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(body: RunCreate, db: DbSession) -> Run:
    run = Run(filename=body.filename, status=RunStatus.PENDING)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@router.get("", response_model=RunListResponse)
async def list_runs(db: DbSession) -> RunListResponse:
    rows = (await db.execute(select(Run).order_by(Run.started_at.desc()))).scalars().all()
    return RunListResponse(runs=list(rows), total=len(rows))


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, db: DbSession) -> Run:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.delete("/{run_id}", status_code=204)
async def delete_run(run_id: str, db: DbSession) -> None:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    await db.delete(run)
    await db.commit()


@router.post("/{run_id}/summary", response_model=SummaryResponse)
async def generate_summary(run_id: str, db: DbSession, llm: LLMClient) -> SummaryResponse:
    """Generate (or re-generate) an AI executive summary for a run."""
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM client not configured.")
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    from grainsift.engine.summarization import generate_run_summary
    try:
        text = await generate_run_summary(run_id, db, llm)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SummaryResponse(run_id=run_id, summary=text)


@router.get("/{run_id}/summary", response_model=SummaryResponse)
async def get_summary(run_id: str, db: DbSession) -> SummaryResponse:
    """Retrieve the previously generated AI summary for a run."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if not run.ai_summary:
        raise HTTPException(status_code=404, detail="No summary generated yet.")
    return SummaryResponse(run_id=run_id, summary=run.ai_summary)
