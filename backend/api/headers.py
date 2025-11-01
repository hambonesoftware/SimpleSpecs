"""Header-related API endpoints."""

from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document, DocumentSection
from ..services.header_match import find_header_occurrences
from ..services.headers import HeadersLLMClient, extract_headers, flatten_outline
from ..services.headers_llm_simple import (
    InvalidLLMJSONError,
    get_headers_llm_json,
)
from ..services.headers_orchestrator import extract_headers_and_chunks
from ..services.pdf_native import parse_pdf
from ..services.sections import build_and_store_sections
from ..services.simpleheaders_state import SimpleHeadersState

router = APIRouter(prefix="/api", tags=["headers"])


@router.post("/headers/{document_id}")
async def compute_headers(
    document_id: int,
    *,
    trace: bool = Query(False, description="Return inline trace events when available"),
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

    if document.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document is missing a primary key",
        )

    use_simple_llm = (
        settings.headers_mode.lower() == "llm_simple"
        and settings.llm_provider.lower() != "disabled"
    )
    if use_simple_llm:
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

    doc_id = int(document.id)
    document_path = settings.upload_dir / str(doc_id) / document.filename
    if not document_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document contents missing",
        )

    try:
        from ..routers import headers as headers_router
    except Exception:  # pragma: no cover - defensive fallback
        headers_router = None

    parse_impl = parse_pdf
    if headers_router is not None:
        parse_impl = getattr(headers_router, "parse_pdf", parse_pdf)
    parse_result = parse_impl(document_path, settings=settings)

    client_factory = HeadersLLMClient
    if headers_router is not None:
        client_factory = getattr(headers_router, "HeadersLLMClient", HeadersLLMClient)
    llm_client = client_factory(settings)
    header_result = extract_headers(
        parse_result,
        settings=settings,
        llm_client=llm_client,
    )
    native_headers = flatten_outline(header_result.outline)

    document_bytes = document_path.read_bytes()
    orchestrator_impl = extract_headers_and_chunks
    if headers_router is not None:
        orchestrator_impl = getattr(
            headers_router, "extract_headers_and_chunks", extract_headers_and_chunks
        )

    orchestrator_kwargs = {
        "settings": settings,
        "native_headers": native_headers,
        "metadata": {
            "filename": document.filename,
            "document_id": doc_id,
        },
        "session": session,
        "document": document,
        "want_trace": trace,
    }
    accepted_params = set(inspect.signature(orchestrator_impl).parameters)
    for key in list(orchestrator_kwargs.keys()):
        if key not in accepted_params:
            orchestrator_kwargs.pop(key)

    orchestrated, tracer = await orchestrator_impl(document_bytes, **orchestrator_kwargs)

    raw_doc_hash = orchestrated.get("doc_hash")
    doc_hash = str(raw_doc_hash) if raw_doc_hash not in {None, ""} else ""
    lines = list(orchestrated.get("lines", []))
    SimpleHeadersState.set(doc_id, doc_hash, lines)

    persisted_sections = build_and_store_sections(
        session=session,
        document_id=doc_id,
        simpleheaders=orchestrated.get("headers", []),
        lines=lines,
    )
    section_key_by_gid = {
        int(section.start_global_idx): section.section_key for section in persisted_sections
    }
    raw_sections = orchestrated.get("sections", []) or []
    if raw_sections:
        sections_payload: list[dict[str, object | None]] = []
        for section in raw_sections:
            start_idx = _coerce_optional_int(section.get("start_global_idx")) or 0
            entry = {
                "section_key": section_key_by_gid.get(start_idx),
                "header_text": section.get("header_text"),
                "header_number": section.get("header_number"),
                "level": _coerce_int(section.get("level"), default=1),
                "start_global_idx": start_idx,
                "end_global_idx": _coerce_optional_int(section.get("end_global_idx"))
                or start_idx,
                "start_page": _coerce_optional_int(section.get("start_page")),
                "end_page": _coerce_optional_int(section.get("end_page")),
            }
            sections_payload.append(entry)
    else:
        sections_payload = [_serialise_section(section) for section in persisted_sections]

    simpleheaders_payload = _serialise_simpleheaders(
        orchestrated.get("headers", []), section_key_by_gid
    )

    fenced_text = orchestrated.get("fenced_text") or header_result.fenced_text
    messages = list(header_result.messages) + list(orchestrated.get("messages", []))

    response_payload: dict[str, object] = {
        "source": header_result.source,
        "document_id": doc_id,
        "outline": header_result.to_json(),
        "simpleheaders": simpleheaders_payload,
        "sections": sections_payload,
        "mode": orchestrated.get("mode"),
        "messages": messages,
        "fenced_text": fenced_text,
        "doc_hash": doc_hash,
        "excluded_pages": orchestrated.get("excluded_pages", []),
    }

    if trace and tracer is not None:
        response_payload["trace"] = {
            "events": tracer.as_list(),
            "path": tracer.path,
            "summary_path": tracer.summary_path,
        }

    return response_payload


def _serialise_simpleheaders(headers: list[dict], section_keys: dict[int, str]) -> list[dict]:
    """Return API-ready simple header entries with section keys."""

    serialised: list[dict] = []
    for header in headers:
        text = str(header.get("text", "")).strip()
        if not text:
            continue

        number = header.get("number")
        level = _coerce_int(header.get("level"), default=1)
        page = _coerce_optional_int(header.get("page"))
        line_idx = _coerce_optional_int(header.get("line_idx"))
        global_idx = _coerce_optional_int(header.get("global_idx"))
        section_key = (
        section_keys.get(global_idx) if global_idx is not None else None
        )

        entry: dict[str, object | None] = {
            "text": text,
            "number": number if number not in {"", None} else None,
            "level": level,
            "page": page,
            "line_idx": line_idx,
            "global_idx": global_idx,
            "section_key": section_key,
        }

        if "source_idx" in header:
            entry["source_idx"] = _coerce_optional_int(header.get("source_idx"))
        if "strategy" in header:
            entry["strategy"] = header.get("strategy")
        if "score" in header:
            entry["score"] = header.get("score")

        serialised.append(entry)

    return serialised


def _serialise_section(section: DocumentSection) -> dict:
    """Convert a ``DocumentSection`` ORM model into a serialisable payload."""

    return {
        "section_key": section.section_key,
        "title": section.title,
        "number": section.number,
        "level": section.level,
        "start_global_idx": section.start_global_idx,
        "end_global_idx": section.end_global_idx,
        "start_page": section.start_page,
        "end_page": section.end_page,
    }


def _coerce_int(value, *, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced


def _coerce_optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
