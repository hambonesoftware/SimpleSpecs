"""Endpoints for header extraction and outline delivery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.headers import (
    HeaderExtractionResult,
    HeaderNode,
    HeadersLLMClient,
    extract_headers,
)
from ..services.pdf_native import parse_pdf

router = APIRouter(prefix="/api", tags=["headers"])


class HeaderNodePayload(BaseModel):
    """Schema for a header node in the outline."""

    title: str
    numbering: str
    page: int | None = None
    children: list["HeaderNodePayload"] = Field(default_factory=list)

    @classmethod
    def from_node(cls, node: HeaderNode) -> "HeaderNodePayload":
        return cls(
            title=node.title,
            numbering=node.numbering,
            page=node.page,
            children=[cls.from_node(child) for child in node.children],
        )


HeaderNodePayload.model_rebuild()


class HeadersResponse(BaseModel):
    """API response structure for header extraction."""

    document_id: int
    source: str
    fenced_text: str
    outline: list[HeaderNodePayload]

    @classmethod
    def from_result(
        cls, document_id: int, result: HeaderExtractionResult
    ) -> "HeadersResponse":
        return cls(
            document_id=document_id,
            source=result.source,
            fenced_text=result.fenced_text,
            outline=[HeaderNodePayload.from_node(node) for node in result.outline],
        )


@router.post("/headers/{document_id}", response_model=HeadersResponse)
async def generate_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> HeadersResponse:
    """Return the hierarchical headers for a stored document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    if document.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document is missing a primary key",
        )

    doc_id = document.id
    document_path = settings.upload_dir / str(doc_id) / document.filename
    if not document_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document contents missing"
        )

    parse_result = parse_pdf(document_path, settings=settings)
    llm_client = HeadersLLMClient(settings)
    result = extract_headers(parse_result, settings=settings, llm_client=llm_client)
    return HeadersResponse.from_result(doc_id, result)


__all__ = ["router"]
