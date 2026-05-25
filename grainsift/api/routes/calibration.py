"""Calibration Runner routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from grainsift.api.deps import DbSession, LLMClient
from grainsift.engine.calibration import CalibrationReport, get_calibration_report, run_calibration
from grainsift.models.database import Run
from grainsift.models.enums import RunStatus

router = APIRouter(prefix="/runs/{run_id}/calibration", tags=["calibration"])


@router.get("", response_model=CalibrationReport)
async def get_calibration(run_id: str, db: DbSession) -> CalibrationReport:
    """Return current calibration state (human stats + saved self-check if any)."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status != RunStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Run must be complete.")
    return await get_calibration_report(run_id, db)


@router.post("", response_model=CalibrationReport)
async def trigger_calibration(
    run_id: str,
    db: DbSession,
    llm: LLMClient,
    sample_size: int = Query(default=20, ge=5, le=50),
) -> CalibrationReport:
    """Run self-consistency check on a random sample and return the full report."""
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not configured — add an API key in Settings.")

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status != RunStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Run must be complete.")

    return await run_calibration(run_id, db, llm, sample_size)
