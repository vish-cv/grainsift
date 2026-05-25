"""Project routes — CRUD for Projects and their run membership."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from grainsift.api.deps import DbSession
from grainsift.models.database import Project, Run
from grainsift.models.schemas import RunListResponse, RunResponse

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    taxonomy_run_id: str | None
    created_at: str
    run_count: int = 0


async def _project_out(project: Project, db: DbSession) -> ProjectOut:
    count = (
        await db.scalar(
            select(func.count()).select_from(Run).where(Run.project_id == project.id)
        )
    ) or 0
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        taxonomy_run_id=project.taxonomy_run_id,
        created_at=project.created_at.isoformat(),
        run_count=count,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: DbSession) -> list[ProjectOut]:
    projects = (
        await db.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()
    return [await _project_out(p, db) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, db: DbSession) -> ProjectOut:
    project = Project(name=body.name, description=body.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return await _project_out(project, db)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: DbSession) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await _project_out(project, db)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectCreate, db: DbSession) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    project.name = body.name
    project.description = body.description
    await db.commit()
    return await _project_out(project, db)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: DbSession) -> None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    await db.delete(project)
    await db.commit()


@router.get("/{project_id}/runs", response_model=RunListResponse)
async def get_project_runs(project_id: str, db: DbSession) -> RunListResponse:
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    rows = (
        await db.execute(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.started_at.desc())
        )
    ).scalars().all()
    return RunListResponse(runs=list(rows), total=len(rows))
