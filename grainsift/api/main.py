"""FastAPI application factory and lifespan."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

from grainsift import __version__
from grainsift.config import get_settings
from grainsift.llm.client import create_llm_client
from sqlalchemy import text

from grainsift.models.database import Base, configure_sqlite_pragmas

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # ── Database setup ────────────────────────────────────────────────────────
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )

    if "sqlite" in settings.database_url:
        configure_sqlite_pragmas(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Incremental migrations for older DBs
    async with engine.begin() as conn:
        cols = (await conn.execute(text("PRAGMA table_info(runs)"))).fetchall()
        col_names = [c[1] for c in cols]
        if "project_id" not in col_names:
            await conn.execute(
                text("ALTER TABLE runs ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
            )
            logger.info("Migration: added project_id column to runs")
        if "ai_summary" not in col_names:
            await conn.execute(text("ALTER TABLE runs ADD COLUMN ai_summary TEXT"))
            logger.info("Migration: added ai_summary column to runs")

    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    # ── LLM client ────────────────────────────────────────────────────────────
    try:
        app.state.llm_client = create_llm_client(settings)
        logger.info(
            "LLM client ready: %s / %s",
            settings.llm_provider,
            settings.active_model,
        )
    except Exception as exc:
        logger.warning("LLM client not configured: %s", exc)
        app.state.llm_client = None

    logger.info("GrainSift %s started", __version__)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await engine.dispose()
    logger.info("GrainSift shut down cleanly")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GrainSift",
        description="Open source, self-hosted feedback analysis pipeline",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    from grainsift.api.routes import calibration, dashboard, discovery, extraction, pipeline, projects, prompts, query, review, runs, settings, upload

    app.include_router(projects.router, prefix="/api")
    app.include_router(prompts.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(upload.router, prefix="/api")
    app.include_router(discovery.router, prefix="/api")
    app.include_router(extraction.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")
    app.include_router(query.router, prefix="/api")
    app.include_router(calibration.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    async def config_info() -> dict[str, object]:
        return {
            "llm_provider": settings.llm_provider,
            "model": settings.active_model,
            "batch_size": settings.batch_size,
            "confidence_threshold": settings.confidence_threshold,
        }

    # ── Serve built React frontend ─────────────────────────────────────────────
    if _FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(_full_path: str) -> FileResponse:
            return FileResponse(str(_FRONTEND_DIST / "index.html"))

    return app
