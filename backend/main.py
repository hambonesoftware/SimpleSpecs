"""SimpleSpecs backend entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .routers import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise application state for the FastAPI app."""

    init_db()
    yield


app = FastAPI(title="SimpleSpecs", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/api/health")
def read_health() -> dict[str, bool]:
    """Health check endpoint returning a simple ok response."""

    return {"ok": True}
