"""FastAPI application entry-point for SimpleSpecs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .app.routers import specs as rag_specs
from .routers import (
    export,
    files,
    headers,
    headers_ollama,
    health,
    ingest,
    parse,
    settings,
    specs as legacy_specs,
    system,
    upload,
)


def _build_app() -> FastAPI:
    """Create and configure a FastAPI application instance."""

    app_settings = get_settings()
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Initialize dependencies and report optional MinerU availability."""

        from .services.pdf_mineru import check_mineru_availability

        init_db()

        refreshed_settings = get_settings()
        available, reason = check_mineru_availability(settings=refreshed_settings)
        if not available and reason:
            print(f"[startup] MinerU unavailable: {reason}")

        yield

    application = FastAPI(title="SimpleSpecs", version="1.0.0", lifespan=lifespan)

    allowed_origins = app_settings.ALLOW_ORIGINS or ["http://localhost:3000"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(upload.router)
    application.include_router(ingest.ingest_router)
    application.include_router(files.files_router)
    application.include_router(parse.router)
    application.include_router(headers.router)
    application.include_router(headers_ollama.router)
    application.include_router(settings.router)
    application.include_router(legacy_specs.router)
    application.include_router(rag_specs.router)
    application.include_router(export.router)
    application.include_router(system.system_router)

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        application.mount(
            "/", StaticFiles(directory=frontend_dir, html=True), name="frontend"
        )

    return application


app = _build_app()


def create_app() -> FastAPI:
    """Compatibility factory returning a configured application."""

    return _build_app()
