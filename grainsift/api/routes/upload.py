"""CSV upload and ingest endpoints."""

from __future__ import annotations

import dataclasses
import json
import logging

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from grainsift.api.deps import AppSettings, DbSession
from grainsift.engine.ingest import ingest_csv, preview_csv
from grainsift.exceptions import IngestError
from grainsift.models.database import Run
from grainsift.models.enums import RunStatus
from grainsift.models.schemas import (
    ColumnMapping,
    IngestRequest,
    IngestResult,
    UploadPreview,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/preview", response_model=UploadPreview)
async def preview_upload(file: UploadFile) -> UploadPreview:
    """
    Parse the first 5 rows and return column names + row count.
    Call this before /ingest so the UI can render the column mapping screen.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {_MAX_UPLOAD_BYTES // 1024 // 1024} MB limit",
        )

    try:
        columns, preview_rows, row_count = preview_csv(content)
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return UploadPreview(
        columns=columns,
        preview_rows=preview_rows,
        row_count_estimate=row_count,
    )


@router.post("/{run_id}/ingest", response_model=IngestResult)
async def ingest_run(
    run_id: str,
    file: UploadFile,
    column_mapping: ColumnMapping,
    db: DbSession,
    settings: AppSettings,
) -> IngestResult:
    """
    Upload a CSV and run Stage 1 ingestion against an existing run.
    Creates and persists raw_feedback rows. Returns ingest statistics.
    """
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status not in (RunStatus.PENDING,):
        raise HTTPException(
            status_code=409,
            detail=f"Run is in '{run.status}' state — can only ingest into a pending run",
        )

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {_MAX_UPLOAD_BYTES // 1024 // 1024} MB limit",
        )

    run.status = RunStatus.INGESTING
    await db.commit()

    try:
        result = await ingest_csv(
            run_id=run_id,
            content=content,
            column_mapping=column_mapping,
            session=db,
            settings=settings,
        )
    except IngestError as exc:
        run.status = RunStatus.FAILED
        await db.commit()
        logger.exception("Ingest failed for run %s", run_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        run.status = RunStatus.FAILED
        await db.commit()
        logger.exception("Unexpected error during ingest for run %s", run_id)
        raise HTTPException(status_code=500, detail="Ingest failed unexpectedly") from exc

    # Ingest done — run is now ready for discovery
    run.status = RunStatus.PENDING
    run.filename = file.filename
    run.summary = json.dumps(dataclasses.asdict(result))
    await db.commit()

    return result


@router.post("/full", response_model=dict, status_code=201)
async def upload_and_create_run(
    file: UploadFile,
    db: DbSession,
    settings: AppSettings,
    feedback_column: str = "feedback",
    date_column: str | None = None,
    source_column: str | None = None,
    project_id: str | None = None,
) -> JSONResponse:
    """
    Convenience endpoint: creates a run + ingests in one call.
    Returns {run_id, ingest_result}.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    run = Run(filename=file.filename, status=RunStatus.INGESTING, project_id=project_id)
    db.add(run)
    await db.commit()
    await db.refresh(run)

    column_mapping = ColumnMapping(
        feedback_column=feedback_column,
        date_column=date_column,
        source_column=source_column,
    )

    try:
        result = await ingest_csv(
            run_id=run.id,
            content=content,
            column_mapping=column_mapping,
            session=db,
            settings=settings,
        )
    except IngestError as exc:
        run.status = RunStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run.status = RunStatus.PENDING
    run.summary = json.dumps(dataclasses.asdict(result))
    await db.commit()

    return JSONResponse(
        status_code=201,
        content={"run_id": run.id, "ingest_result": dataclasses.asdict(result)},
    )
