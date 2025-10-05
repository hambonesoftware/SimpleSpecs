"""FastAPI application entry-point for SimpleSpecs."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .routers import (
    export,
    files,
    health,
    headers,
    headers_ollama,
    ingest,
    settings,
    specs,
    system,
    upload,
)

app = FastAPI(title="SimpleSpecs", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(upload.router)
app.include_router(ingest.ingest_router)
app.include_router(files.files_router)
app.include_router(headers.router)
app.include_router(headers_ollama.router)
app.include_router(settings.router)
app.include_router(specs.router)
app.include_router(export.router)
app.include_router(system.system_router)

@app.on_event("startup")
def _on_startup() -> None:
    """Prepare services and emit startup diagnostics."""

    from .services.pdf_mineru import check_mineru_availability

    init_db()

    settings = get_settings()
    available, reason = check_mineru_availability(settings=settings)
    if not available and reason:
        print(f"[startup] MinerU unavailable: {reason}")

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def create_app() -> FastAPI:
    """Compatibility factory returning the configured application."""

    return app
