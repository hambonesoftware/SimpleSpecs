"""Document retrieval endpoints backed by persisted artifacts."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..database import get_session
from ..models import (
    Document,
    DocumentArtifact,
    DocumentArtifactType,
    DocumentPage,
    DocumentSection,
    DocumentTable,
)
from ..services.pdf_native import collect_line_metrics
from ..services.simpleheaders_state import SimpleHeadersState
from ..services.outline_cache import latest_outline_for_document

router = APIRouter(prefix="/api", tags=["documents"])


def _compute_lines_hash(lines: list[dict]) -> str:
    """Return a deterministic hash for cached line entries."""

    digest = hashlib.sha256()
    for entry in lines:
        digest.update(str(entry.get("global_idx")).encode("utf-8", "ignore"))
        digest.update(b"|")
        digest.update(str(entry.get("text", "")).encode("utf-8", "ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


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


def _ensure_section_cache(
    *,
    document: Document,
    doc_hash: str,
    settings: Settings,
    payload: dict | None = None,
) -> None:
    """Populate :class:`SimpleHeadersState` when missing for ``document``."""

    if document.id is None:
        return

    cached = SimpleHeadersState.get(document.id)
    if cached is not None:
        cached_hash, cached_lines = cached
        if cached_lines and (not doc_hash or cached_hash == doc_hash):
            return

    if payload:
        raw_lines = payload.get("lines")
        if isinstance(raw_lines, list) and raw_lines:
            lines: list[dict] = []
            for entry in raw_lines:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text", ""))
                global_idx = entry.get("global_idx")
                try:
                    global_idx_int = int(global_idx) if global_idx is not None else None
                except (TypeError, ValueError):
                    global_idx_int = None
                if global_idx_int is None:
                    continue
                lines.append({
                    **entry,
                    "text": text,
                    "global_idx": global_idx_int,
                })
            if lines:
                cache_hash = doc_hash or _compute_lines_hash(lines)
                SimpleHeadersState.set(document.id, cache_hash, lines)
                return

    document_path = settings.upload_dir / str(document.id) / document.filename
    if not document_path.exists():
        return

    try:
        document_bytes = document_path.read_bytes()
    except OSError:
        return

    try:
        lines, _, computed_hash = collect_line_metrics(
            document_bytes,
            {"document_id": document.id, "filename": document.filename},
            suppress_toc=settings.headers_suppress_toc,
            suppress_running=settings.headers_suppress_running,
            tracer=None,
        )
    except Exception:
        return

    if not lines:
        return

    cache_hash = doc_hash or computed_hash
    SimpleHeadersState.set(document.id, cache_hash, lines)


@router.get(
    "/documents/{document_id}/headers", response_model=StoredHeadersResponse
)
async def get_cached_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
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

    payload = dict(artifact.body or {})
    doc_hash = str(payload.get("doc_hash", "") or "")
    _ensure_section_cache(
        document=document,
        doc_hash=doc_hash,
        settings=settings,
        payload=payload,
    )
    return StoredHeadersResponse(
        headers=list(payload.get("headers", [])),
        sections=list(payload.get("sections", [])),
        mode=payload.get("mode"),
        messages=list(payload.get("messages", [])),
        doc_hash=payload.get("doc_hash"),
        created_at=artifact.created_at.isoformat() if artifact.created_at else None,
    )


@router.get("/documents/{document_id}/status")
def document_status(
    document_id: int,
    *,
    session: Session = Depends(get_session),
):
    """Return parse/header availability flags for the given document."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    parsed = bool(document.last_parsed_at)

    outline_cache = latest_outline_for_document(session, document_id)
    has_sections = session.exec(
        select(DocumentSection.id)
        .where(DocumentSection.document_id == document_id)
        .limit(1)
    ).first() is not None
    headers_ready = bool(outline_cache and has_sections)

    return {"parsed": parsed, "headers": headers_ready}


__all__ = ["router"]

