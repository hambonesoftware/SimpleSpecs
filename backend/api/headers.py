"""Header-related API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document, DocumentSection
from ..services.header_match import find_header_occurrences
from ..services.headers_llm_simple import (
    InvalidLLMJSONError,
    get_headers_llm_json,
)
from ..services.simpleheaders_state import SimpleHeadersState

router = APIRouter(prefix="/api", tags=["headers"])


@router.post("/headers/{document_id}")
def compute_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Return LLM-provided headers and alignment matches for ``document_id``."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    try:
        llm_obj = get_headers_llm_json(document_id, session, settings)
    except InvalidLLMJSONError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "invalid_llm_json"},
        )

    matches = find_header_occurrences(
        session, document_id, llm_obj.get("headers", [])
    )
    return {"llm_headers": llm_obj.get("headers", []), "matches": matches}


@router.get("/headers/{document_id}/section-text", response_class=PlainTextResponse)
def section_text(
    document_id: int,
    start: int,
    end: int,
    *,
    section_key: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Return the plain text for a section bounded by global indices."""

    if start < 0 or end < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid section bounds",
        )

    if end < start:
        start, end = end, start

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    section_record = None
    if section_key:
        section_record = session.exec(
            select(DocumentSection).where(
                DocumentSection.document_id == document_id,
                DocumentSection.section_key == section_key,
            )
        ).first()
        if section_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Section not found for this document",
            )

    cached = SimpleHeadersState.get(document_id)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No section data available for this document",
        )

    _, lines = cached
    if section_record is not None:
        start = max(start, section_record.start_global_idx)
        end = min(end, section_record.end_global_idx - 1)
        if end < start:
            end = start

    text_lines = [
        str(line.get("text", ""))
        for line in lines
        if start <= int(line.get("global_idx", -1)) <= end
    ]

    return PlainTextResponse("\n".join(text_lines))


__all__ = ["router"]
