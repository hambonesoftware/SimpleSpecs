"""FastAPI application for the spec-search pipeline."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .spec_search.router import router as spec_search_router
from .spec_extraction.router import router as spec_extraction_router

app = FastAPI(title="SimpleSpecs Spec Search", version="1.0.0")

app.include_router(spec_search_router)
app.include_router(spec_extraction_router)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
