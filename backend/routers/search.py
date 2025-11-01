"""Endpoints for section-gated document search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..database import get_session
from ..models import Document, DocumentSection
from ..services.sections import route_query_to_sections, search_in_sections
from ..services.simpleheaders_state import SimpleHeadersState

router = APIRouter(prefix="/api", tags=["search"])


class SectionSearchMatch(BaseModel):
    """Line-level match within a document section."""

    section_key: str
    section_title: str
    section_number: str | None = None
    score: float
    text: str
    line_global_idx: int
    page: int | None = None
    start_global_idx: int
    end_global_idx: int
    start_page: int | None = None
    end_page: int | None = None


class SectionSearchResponse(BaseModel):
    """Response payload for section-gated search queries."""

    document_id: int
    query: str
    section_key: str | None = None
    routed_section_keys: list[str] = Field(default_factory=list)
    matches: list[SectionSearchMatch] = Field(default_factory=list)


@router.get("/search", response_model=SectionSearchResponse)
def search_document_sections(
    *,
    session: Session = Depends(get_session),
    doc: int = Query(..., alias="doc", ge=1),
    q: str = Query(..., alias="q"),
    section_key: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> SectionSearchResponse:
    """Return ranked matches for ``q`` filtered by document sections."""

    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must not be empty",
        )

    document = session.get(Document, doc)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    cached = SimpleHeadersState.get(doc)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Header data unavailable for this document",
        )

    _, lines = cached

    routed_keys: list[str] = []
    target_keys: list[str]

    if section_key:
        exists = session.exec(
            select(DocumentSection.section_key).where(
                DocumentSection.document_id == doc,
                DocumentSection.section_key == section_key,
            )
        ).first()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Section not found for this document",
            )
        target_keys = [section_key]
    else:
        routed_keys = route_query_to_sections(
            session=session, document_id=doc, query=query
        )
        target_keys = routed_keys

    matches_raw = search_in_sections(
        session=session,
        document_id=doc,
        query=query,
        section_keys=target_keys,
        lines=lines,
        limit=limit,
    )
    matches = [SectionSearchMatch(**match) for match in matches_raw]

    return SectionSearchResponse(
        document_id=doc,
        query=query,
        section_key=section_key,
        routed_section_keys=routed_keys,
        matches=matches,
    )


__all__ = ["router"]

