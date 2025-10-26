"""SimpleSpecs backend entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import api_router
from .middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from .observability import RequestMetricsMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise application state for the FastAPI app."""

    init_db()
    yield


app = FastAPI(title="SimpleSpecs", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(api_router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend-static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index() -> FileResponse:
        """Return the compiled frontend entrypoint."""

        return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def read_health() -> dict[str, bool]:
    """Health check endpoint returning a simple ok response."""

    return {"ok": True}
