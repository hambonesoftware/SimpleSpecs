"""SimpleSpecs backend entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from .database import init_db
from .routers import api_router

app = FastAPI(title="SimpleSpecs", version="0.1.0")
app.include_router(api_router)


@app.on_event("startup")
def on_startup() -> None:
    """Initialise application state."""

    init_db()


@app.get("/api/health")
def read_health() -> dict[str, bool]:
    """Health check endpoint returning a simple ok response."""

    return {"ok": True}
