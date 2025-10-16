"""RAG specification endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...models import SpecItem
from ...services.spec_rag import export_specs, extract_specs, index_specs, search_specs
from ...services.spec_rag import load_spec_items

router = APIRouter(prefix="/api/specs", tags=["specs-rag"])


class SpecFileRequest(BaseModel):
    file_id: str = Field(..., min_length=1)


class SpecIndexResponse(BaseModel):
    file_id: str
    indexed: int


class SpecSearchRequest(SpecFileRequest):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class SpecSearchHit(BaseModel):
    chunk_id: str
    score: float
    bm25: float
    vector: float
    text: str
    metadata: dict[str, Any]


@router.post("/extract", response_model=list[SpecItem])
def extract_endpoint(payload: SpecFileRequest) -> list[SpecItem]:
    """Run deterministic extraction for a file."""

    try:
        return extract_specs(payload.file_id)
    except FileNotFoundError as exc:  # pragma: no cover - error branch
        detail = str(exc) or "Required artifacts are missing."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


@router.post("/index", response_model=SpecIndexResponse)
def index_endpoint(payload: SpecFileRequest) -> SpecIndexResponse:
    """Persist the hybrid index for a file's specs."""

    try:
        try:
            specs = load_spec_items(payload.file_id)
        except FileNotFoundError:
            specs = extract_specs(payload.file_id)
        index_specs(payload.file_id, specs=specs)
    except FileNotFoundError as exc:  # pragma: no cover - error branch
        detail = str(exc) or "Required artifacts are missing."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    return SpecIndexResponse(file_id=payload.file_id, indexed=len(specs))


@router.post("/search", response_model=list[SpecSearchHit])
def search_endpoint(payload: SpecSearchRequest) -> list[SpecSearchHit]:
    """Search the indexed specifications."""

    try:
        hits = search_specs(payload.file_id, payload.query, top_k=payload.top_k)
    except FileNotFoundError as exc:  # pragma: no cover - error branch
        detail = str(exc) or "Specification index not found."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    return [SpecSearchHit.model_validate(hit) for hit in hits]


@router.post("/export", response_model=dict[str, Any])
def export_endpoint(payload: SpecFileRequest) -> dict[str, Any]:
    """Return the persisted specification payload."""

    try:
        return export_specs(payload.file_id)
    except FileNotFoundError as exc:  # pragma: no cover - error branch
        detail = str(exc) or "Specifications not found."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
