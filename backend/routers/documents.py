"""Document retrieval endpoints backed by persisted artifacts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlmodel import Session

from ..database import get_session
from ..models import (
    Document,
    DocumentArtifact,
    DocumentArtifactType,
    DocumentPage,
    DocumentTable,
)

router = APIRouter(prefix="/api", tags=["documents"])


class PageBlockPayload(BaseModel):
    """Schema describing a stored page block."""

    text: str
    bbox: tuple[float, float, float, float]
    font: str | None = None
    font_size: float | None = None
    source: str | None = None


class DocumentPagePayload(BaseModel):
    """Page payload containing raw text and layout information."""

    page_index: int
    width: float
    height: float
    text_raw: str
    layout: list[PageBlockPayload] = Field(default_factory=list)


class TablePayload(BaseModel):
    """Representation of a stored table marker."""

    page_index: int
    bbox: tuple[float, float, float, float]
    flavor: str | None = None
    accuracy: float | None = None


class StoredHeadersResponse(BaseModel):
    """Cached header tree retrieved from the artifact store."""

    headers: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    mode: str | None = None
    messages: list[str] = Field(default_factory=list)
    doc_hash: str | None = None
    created_at: str | None = None


@router.get("/documents/{document_id}", response_model=Document)
async def get_document(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> Document:
    """Return stored metadata for a document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return document


@router.get(
    "/documents/{document_id}/pages", response_model=list[DocumentPagePayload]
)
async def get_document_pages(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> list[DocumentPagePayload]:
    """Return persisted page layouts for a document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    statement = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_index)
    )
    pages = session.exec(statement).all()

    payload: list[DocumentPagePayload] = []
    for page in pages:
        layout_blocks = []
        for block in page.layout:
            bbox_values = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
            layout_blocks.append(
                PageBlockPayload(
                    text=str(block.get("text", "")),
                    bbox=bbox_values,  # type: ignore[arg-type]
                    font=block.get("font"),
                    font_size=block.get("font_size"),
                    source=block.get("source"),
                )
            )
        payload.append(
            DocumentPagePayload(
                page_index=page.page_index,
                width=page.width,
                height=page.height,
                text_raw=page.text_raw,
                layout=layout_blocks,
            )
        )

    return payload


@router.get(
    "/documents/{document_id}/tables", response_model=list[TablePayload]
)
async def get_document_tables(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> list[TablePayload]:
    """Return detected table markers for a document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    statement = (
        select(DocumentTable)
        .where(DocumentTable.document_id == document_id)
        .order_by(DocumentTable.page_index)
    )
    tables = session.exec(statement).all()
    payload: list[TablePayload] = []
    for table in tables:
        bbox_values = tuple(float(value) for value in table.bbox)
        payload.append(
            TablePayload(
                page_index=table.page_index,
                bbox=bbox_values,  # type: ignore[arg-type]
                flavor=table.flavor,
                accuracy=table.accuracy,
            )
        )
    return payload


@router.get(
    "/documents/{document_id}/headers", response_model=StoredHeadersResponse
)
async def get_cached_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> StoredHeadersResponse:
    """Return the most recent cached header tree for a document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    statement = (
        select(DocumentArtifact)
        .where(
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.artifact_type == DocumentArtifactType.HEADER_TREE,
        )
        .order_by(desc(DocumentArtifact.created_at))
    )
    artifact = session.exec(statement).first()
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No cached headers"
        )

    payload = dict(artifact.body)
    return StoredHeadersResponse(
        headers=list(payload.get("headers", [])),
        sections=list(payload.get("sections", [])),
        mode=payload.get("mode"),
        messages=list(payload.get("messages", [])),
        doc_hash=payload.get("doc_hash"),
        created_at=artifact.created_at.isoformat() if artifact.created_at else None,
    )


__all__ = ["router"]

