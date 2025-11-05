"""Specification extraction and approval endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.artifact_store import get_or_create_parse_result
from ..services.pdf_native import parse_pdf
from ..services.spec_extraction import (
    SpecExtractionResult,
    SpecLine,
    SpecLLMClient,
    extract_specifications,
)
from ..services.spec_records import (
    SpecRecordError,
    approve_specifications,
    ensure_document,
    export_spec_record,
    fetch_spec_record,
    wipe_spec_buckets_for_document,  # <-- required for rerun
)

router = APIRouter(prefix="/api", tags=["specifications"])


def _document_id(document: Document) -> int:
    """Return the document id or raise an internal error if missing."""
    if document.id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document is missing a primary key",
        )
    return document.id


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    doc_id = _document_id(document)
    document_path = settings.upload_dir / str(doc_id) / document.filename
    if not document_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document contents missing"
        )

    parse_result, _ = get_or_create_parse_result(
        session=session,
        document=document,
        document_path=document_path,
        settings=settings,
        parse_func=parse_pdf,
    )
    llm_client = SpecLLMClient(settings)
    extraction = extract_specifications(
        parse_result, settings=settings, llm_client=llm_client
    )
    return SpecExtractionResponse.from_result(doc_id, extraction)


class SpecAuditEntryPayload(BaseModel):
    """Serialised audit entry for specification approvals and exports."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    actor: str | None = None
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SpecRecordPayload(BaseModel):
    """Serialised view of a frozen specification record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    state: str
    reviewer: str | None = None
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
    frozen_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SpecRecordEnvelope(BaseModel):
    """Envelope containing the current record and associated audit trail."""

    document_id: int
    record: SpecRecordPayload | None = None
    audit: list[SpecAuditEntryPayload] = Field(default_factory=list)


class SpecApprovalRequest(BaseModel):
    """Request body for approving and freezing specifications."""

    reviewer: str = Field(min_length=1)
    payload: dict[str, Any]
    notes: str | None = Field(default=None, max_length=2000)


def _serialize_envelope(*, document_id: int, record, audit: list) -> SpecRecordEnvelope:
    record_payload = (
        SpecRecordPayload.model_validate(record, from_attributes=True)
        if record is not None
        else None
    )
    if record_payload and record_payload.payload is None:
        record_payload.payload = {}
    audit_payload = [
        SpecAuditEntryPayload.model_validate(entry, from_attributes=True)
        for entry in audit
    ]
    return SpecRecordEnvelope(
        document_id=document_id, record=record_payload, audit=audit_payload
    )


@router.get("/specs/{document_id}", response_model=SpecRecordEnvelope)
async def get_spec_record(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> SpecRecordEnvelope:
    """Return the frozen specification record (if available) and audit trail."""
    try:
        document = ensure_document(session, document_id)
    except SpecRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    doc_id = _document_id(document)
    record, audit_entries = fetch_spec_record(session, document_id=doc_id)
    return _serialize_envelope(document_id=doc_id, record=record, audit=audit_entries)


@router.post("/specs/{document_id}/approve", response_model=SpecRecordEnvelope)
async def approve_spec_record(
    document_id: int,
    request: SpecApprovalRequest,
    *,
    session: Session = Depends(get_session),
) -> SpecRecordEnvelope:
    """Freeze specification payload for a document and record an audit entry."""
    try:
        document = ensure_document(session, document_id)
    except SpecRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    reviewer = request.reviewer.strip()
    if not reviewer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reviewer is required"
        )

    try:
        approve_specifications(
            session,
            document=document,
            payload=request.payload,
            reviewer=reviewer,
            notes=request.notes.strip() if request.notes else None,
        )
    except SpecRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    doc_id = _document_id(document)
    record, audit_entries = fetch_spec_record(session, document_id=doc_id)
    return _serialize_envelope(document_id=doc_id, record=record, audit=audit_entries)


@router.get("/specs/{document_id}/export")
async def export_spec_record_endpoint(
    document_id: int,
    *,
    fmt: Literal["csv", "docx"],
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Generate a CSV bundle or DOCX export for an approved specification record."""
    try:
        document = ensure_document(session, document_id)
    except SpecRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    doc_id = _document_id(document)
    record, _ = fetch_spec_record(session, document_id=doc_id)
    if record is None or record.state != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document has no approved specification record",
        )

    try:
        path, media_type = export_spec_record(
            session,
            record=record,
            settings=settings,
            fmt=fmt,
            actor="api",
        )
    except SpecRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return FileResponse(path, media_type=media_type, filename=path.name)


# ---- RERUN SPECS SUPPORT ----------------------------------------------------


@router.delete("/specs/{document_id}/buckets", response_class=Response)
async def delete_spec_buckets(
    document_id: int,
    *,
    session: Session = Depends(get_session),
) -> None:
    """
    Wipe any persisted spec buckets / record state for this document so that the
    next extraction call recomputes everything from scratch.
    """
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    wipe_spec_buckets_for_document(session, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
