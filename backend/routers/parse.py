"""Parsing endpoints for PDF documents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.artifact_store import get_or_create_parse_result
from ..services.pdf_native import ParseResult, parse_pdf

router = APIRouter(prefix="/api", tags=["parse"])


class BlockPayload(BaseModel):
    """Schema representing an extracted text block."""

    text: str
    bbox: tuple[float, float, float, float]
    font: str | None = None
    font_size: float | None = None
    source: str


class TablePayload(BaseModel):
    """Schema describing a detected table marker."""

    bbox: tuple[float, float, float, float]
    flavor: str | None = None
    accuracy: float | None = None


class PagePayload(BaseModel):
    """Schema for a parsed page of a PDF document."""

    page_number: int
    width: float
    height: float
    blocks: list[BlockPayload]
    tables: list[TablePayload] = Field(default_factory=list)
    is_toc: bool = False


class ParseResponse(BaseModel):
    """Complete response payload for a parsed document."""

    document_id: int
    has_ocr: bool
    used_mineru: bool
    pages: list[PagePayload]


@router.post("/parse/{document_id}", response_model=ParseResponse)
async def parse_document(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ParseResponse:
    """Parse a stored document and return extracted blocks, tables, and metadata."""

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

    result, _ = get_or_create_parse_result(
        session=session,
        document=document,
        document_path=document_path,
        settings=settings,
        parse_func=parse_pdf,
    )
    payload = result.to_dict()
    return ParseResponse(document_id=doc_id, **payload)


__all__ = ["router"]
