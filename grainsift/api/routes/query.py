"""Query Engine routes — natural language Q&A over labeled feedback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grainsift.api.deps import DbSession, LLMClient
from grainsift.engine.query import QueryAnswer, answer_question, get_query_history
from grainsift.models.database import Run
from grainsift.models.enums import RunStatus

router = APIRouter(prefix="/runs/{run_id}/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    session_id: str | None = None


class QueryResponse(BaseModel):
    session_id: str
    answer: QueryAnswer


class QueryMessageOut(BaseModel):
    id: str
    question: str
    answer: str
    key_insights: list[str]
    sources: list[dict[str, Any]]
    confidence: str
    created_at: str


class QuerySessionOut(BaseModel):
    session_id: str
    started_at: str
    messages: list[QueryMessageOut]


@router.post("", response_model=QueryResponse)
async def query_run(
    run_id: str,
    body: QueryRequest,
    db: DbSession,
    llm: LLMClient,
) -> QueryResponse:
    """Answer a natural language question about the run's labeled feedback."""
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="LLM not configured — add an API key in Settings.",
        )

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status != RunStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Run must be complete before querying.")

    try:
        answer, session_id = await answer_question(
            run_id=run_id,
            question=body.question,
            session=db,
            llm=llm,
            session_id=body.session_id,
        )
        return QueryResponse(session_id=session_id, answer=answer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/history", response_model=list[QuerySessionOut])
async def query_history(run_id: str, db: DbSession) -> list[QuerySessionOut]:
    """Return all Q&A sessions for this run, newest session first."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    sessions = await get_query_history(run_id, db)
    return [
        QuerySessionOut(
            session_id=s["session_id"],
            started_at=s["started_at"],
            messages=[QueryMessageOut(**m) for m in s["messages"]],
        )
        for s in sessions
    ]
