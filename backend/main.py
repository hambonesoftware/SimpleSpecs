"""SimpleSpecs backend entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterable
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from .observability import RequestMetricsMiddleware
from .paths import EXPORT_DIR, FRONTEND_DIR, UPLOAD_DIR
from .routers import (
    compare,
    documents,
    files,
    headers,
    health,
    observability,
    parse,
    search,
    specs,
    specs_buckets,  # NEW: adds wipe + rerun endpoints for spec buckets
)
from .spec_extraction.router import router as spec_extraction_router

settings = get_settings()
logger = logging.getLogger("uvicorn.error")

cors_allow_origins = list(settings.cors_allow_origins)
allow_credentials = True
if "*" in cors_allow_origins:
    cors_allow_origins = ["*"]
    allow_credentials = False
if not cors_allow_origins:
    cors_allow_origins = ["http://localhost:3600", "http://127.0.0.1:3600"]

_cors_origin_pattern = (
    re.compile(settings.cors_allow_origin_regex)
    if settings.cors_allow_origin_regex
    else None
)


def _mask_api_key(value: str | None) -> str:
    """Return a masked representation of the OpenRouter API key."""
    if not value:
        return "<missing>"

    stripped = value.strip()
    if not stripped:
        return "<missing>"

    if len(stripped) <= 8:
        middle = "…" * max(len(stripped) - 2, 1)
        return f"{stripped[0]}{middle}{stripped[-1]}"

    return f"{stripped[:4]}…{stripped[-4:]}"


def _announce_openrouter_api_key(value: str | None) -> None:
    """Log the OpenRouter API key status to the command window."""
    if value and value.strip():
        masked = _mask_api_key(value)
        message = (
            "[SimpleSpecs] OpenRouter API key loaded from environment (.env): "
            f"{masked}"
        )
    else:
        message = (
            "[SimpleSpecs] OpenRouter API key not found in environment (.env); "
            "OpenRouter-dependent features are disabled."
        )

    logger.info(message)


_announce_openrouter_api_key(settings.openrouter_api_key)


def _ensure_storage_dirs() -> None:
    """Ensure upload/export directories exist before handling requests."""
    # Settings validators also create these paths, but ensure they exist even if
    # settings are overridden in tests.
    for path in {
        UPLOAD_DIR,
        EXPORT_DIR,
        settings.upload_dir,
        settings.export_dir,
        settings.headers_log_dir,
    }:
        Path(path).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise application state for the FastAPI app."""
    init_db()
    _ensure_storage_dirs()
    yield


app = FastAPI(title="SimpleSpecs", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=settings.cors_allow_origin_regex,
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

ROUTERS: Iterable = (
    files.router,
    documents.router,
    headers.router,
    health.router,
    parse.router,
    search.router,
    specs_buckets.router,  # NEW: exposes /api/specs/{id}/buckets + /run-again
    spec_extraction_router,
    specs.router,
    compare.router,
    observability.router,
)

for router in ROUTERS:
    app.include_router(router)


@app.exception_handler(Exception)
async def handle_unexpected_exception(
    request: Request, exc: Exception
) -> JSONResponse:
    """Ensure unexpected exceptions return a JSON payload."""
    logger.exception(
        "Unhandled exception while processing %s %s", request.method, request.url.path
    )
    origin = request.headers.get("origin")
    headers: dict[str, str] = {}

    if origin:
        allowed_origin: str | None = None

        if cors_allow_origins == ["*"]:
            allowed_origin = "*"
        elif origin in cors_allow_origins:
            allowed_origin = origin
        elif _cors_origin_pattern and _cors_origin_pattern.fullmatch(origin):
            allowed_origin = origin

        if allowed_origin:
            headers["Access-Control-Allow-Origin"] = allowed_origin
            headers.setdefault("Vary", "Origin")
            if allow_credentials and allowed_origin != "*":
                headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers=headers or None,
    )


if FRONTEND_DIR.exists():
    static_dir = FRONTEND_DIR / "static"
    if static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(static_dir), html=False),
            name="frontend-static",
        )
    else:
        app.mount(
            "/static",
            StaticFiles(directory=str(FRONTEND_DIR), html=False),
            name="frontend-static",
        )

    @app.get("/", include_in_schema=False)
    async def serve_frontend() -> FileResponse:
        """Return the compiled frontend HTML shell."""
        return FileResponse(FRONTEND_DIR / "index.html")


__all__ = ["app", "UPLOAD_DIR", "EXPORT_DIR", "FRONTEND_DIR"]
