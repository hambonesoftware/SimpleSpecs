"""Specification extraction endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.pdf_native import parse_pdf
from ..services.spec_extraction import (
    SpecExtractionResult,
    SpecLine,
    SpecLLMClient,
    extract_specifications,
)

router = APIRouter(prefix="/api", tags=["specifications"])


class SpecProvenancePayload(BaseModel):
    """Provenance metadata for a specification line."""

    page: int
    block_index: int
    line_index: int
    bbox: list[float] | None = None


class SpecLinePayload(BaseModel):
    """Payload describing a classified specification line."""

    text: str
    page: int
    header_path: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    source: str
    provenance: SpecProvenancePayload

    @classmethod
    def from_line(cls, line: SpecLine) -> "SpecLinePayload":
        data = line.to_dict()
        return cls(
            text=data["text"],
            page=data["page"],
            header_path=list(data.get("header_path", [])),
            disciplines=list(data.get("disciplines", [])),
            scores=dict(data.get("scores", {})),
            source=data.get("source", "rule"),
            provenance=SpecProvenancePayload(**data.get("provenance", {})),
        )


class SpecExtractionResponse(BaseModel):
    """API response containing per-discipline specification buckets."""

    document_id: int
    buckets: dict[str, list[SpecLinePayload]]

    @classmethod
    def from_result(
        cls, document_id: int, result: SpecExtractionResult
    ) -> "SpecExtractionResponse":
        buckets: dict[str, list[SpecLinePayload]] = {}
        raw_buckets = result.to_dict()
        for discipline, items in raw_buckets.items():
            buckets[discipline] = [SpecLinePayload(**item) for item in items]
        return cls(document_id=document_id, buckets=buckets)


@router.post("/specs/extract/{document_id}", response_model=SpecExtractionResponse)
async def extract_specs_endpoint(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SpecExtractionResponse:
    """Return classified specification lines for a stored document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    document_path = settings.upload_dir / str(document.id) / document.filename
    if not document_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document contents missing"
        )

    parse_result = parse_pdf(document_path, settings=settings)
    llm_client = SpecLLMClient(settings)
    extraction = extract_specifications(parse_result, settings=settings, llm_client=llm_client)
    return SpecExtractionResponse.from_result(document.id, extraction)


__all__ = ["router"]
