"""Header-related API endpoints."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import desc
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..database import get_session
from ..models import (
    Document,
    DocumentArtifact,
    DocumentArtifactType,
    DocumentSection,
    HeaderOutlineRun,
)
from ..services.artifact_store import get_or_create_parse_result
from ..services.header_match import find_header_occurrences
from ..services.headers import (
    HeadersLLMClient,
    build_outline_from_simpleheaders,
    extract_headers,
    flatten_outline,
)
from ..services.headers_llm_simple import (
    InvalidLLMJSONError,
    get_headers_llm_json,
)
from ..services.headers_orchestrator import (
    extract_headers_and_chunks as orchestrate_headers_and_chunks,
)
from ..spec_extraction.jobs import persist_sections
from ..services.pdf_native import collect_line_metrics, parse_pdf
from ..services.sections import build_and_store_sections, delete_sections_for_document
from ..services.simpleheaders_state import SimpleHeadersState
from ..services.outline_cache import latest_outline_for_document

router = APIRouter(prefix="/api", tags=["headers"])


def _compute_lines_hash(lines: list[dict]) -> str:
    """Return a deterministic hash for cached line entries."""

    digest = hashlib.sha256()
    for entry in lines:
        digest.update(str(entry.get("global_idx")).encode("utf-8", "ignore"))
        digest.update(b"|")
        digest.update(str(entry.get("text", "")).encode("utf-8", "ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


def _hydrate_simpleheaders_state(
    *,
    document: Document,
    settings: Settings,
    doc_hash: str,
    payload: Optional[dict],
) -> None:
    """Ensure :class:`SimpleHeadersState` is hydrated for ``document``."""

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
                normalised = dict(entry)
                normalised["text"] = text
                normalised["global_idx"] = global_idx_int
                lines.append(normalised)
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


def _serialise_section_model(section: DocumentSection) -> dict[str, Any]:
    """Return a serialisable representation of a persisted section."""

    section_id = int(section.id) if section.id is not None else None
    payload: dict[str, Any] = {
        "id": section_id,
        "documentId": section.document_id,
        "sectionKey": section.section_key,
        "title": section.title,
        "number": section.number,
        "level": section.level,
        "start_page": section.start_page,
        "end_page": section.end_page,
        "startGlobalIdx": section.start_global_idx,
        "endGlobalIdx": section.end_global_idx,
        "page": section.start_page,
        "globalIdx": section.start_global_idx,
        "bbox": None,
    }

    # Legacy keys used by existing UI helpers.
    payload.setdefault("start_page", section.start_page)
    payload.setdefault("end_page", section.end_page)
    payload.setdefault("start_global_idx", section.start_global_idx)
    payload.setdefault("end_global_idx", section.end_global_idx)

    return payload


def _serialise_simpleheader_from_section(section: DocumentSection) -> dict[str, Any]:
    """Build a SimpleHeaders-style entry from a section row."""

    return {
        "text": section.title,
        "number": section.number,
        "level": section.level,
        "page": section.start_page,
        "line_idx": None,
        "global_idx": section.start_global_idx,
        "section_key": section.section_key,
    }


def _build_meta_payload(
    run: HeaderOutlineRun,
    cache: "HeaderOutlineCache",
) -> dict[str, Any]:
    """Merge stored metadata with runtime attributes."""

    extra: dict[str, Any] = {}
    if cache.meta_json:
        try:
            candidate = json.loads(cache.meta_json)
        except json.JSONDecodeError:
            candidate = {}
        if isinstance(candidate, dict):
            extra = candidate

    meta = dict(extra)
    meta.update(
        {
            "model": run.model,
            "promptHash": run.prompt_hash,
            "sourceHash": run.source_hash,
            "tokens": {
                "prompt": cache.tokens_prompt,
                "completion": cache.tokens_completion,
            },
            "latencyMs": cache.latency_ms,
            "createdAt": run.created_at.isoformat() if run.created_at else None,
        }
    )
    return meta


def get_headers_from_db(
    session: Session,
    document_id: int,
    *,
    settings: Settings,
    document: Optional[Document] = None,
) -> Optional[dict[str, Any]]:
    """Return persisted headers for ``document_id`` when available."""

    document = document or session.get(Document, document_id)
    if document is None:
        return None

    cache = latest_outline_for_document(session, document_id)
    if cache is None:
        return None

    run = session.get(HeaderOutlineRun, cache.run_id)
    if run is None or run.status != "completed":
        return None

    try:
        outline = json.loads(cache.outline_json)
    except json.JSONDecodeError:
        outline = None

    sections = session.exec(
        select(DocumentSection)
        .where(DocumentSection.document_id == document_id)
        .order_by(DocumentSection.start_global_idx.asc())
    ).all()

    sections_payload = [_serialise_section_model(section) for section in sections]
    simpleheaders = [
        _serialise_simpleheader_from_section(section)
        for section in sections
    ]

    artifact = session.exec(
        select(DocumentArtifact)
        .where(
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.artifact_type == DocumentArtifactType.HEADER_TREE,
        )
        .order_by(desc(DocumentArtifact.created_at))
    ).first()
    artifact_payload = dict(artifact.body or {}) if artifact else {}

    meta = _build_meta_payload(run, cache)
    doc_hash = str(
        meta.get("doc_hash")
        or artifact_payload.get("doc_hash")
        or ""
    )

    _hydrate_simpleheaders_state(
        document=document,
        settings=settings,
        doc_hash=doc_hash,
        payload=artifact_payload if artifact_payload else None,
    )

    payload: dict[str, Any] = {
        "documentId": document_id,
        "runId": int(run.id or 0),
        "outline": outline,
        "meta": meta,
        "sections": sections_payload,
        "simpleheaders": simpleheaders,
    }

    if doc_hash:
        payload["docHash"] = doc_hash

    if artifact_payload.get("mode"):
        payload["mode"] = artifact_payload["mode"]

    messages = artifact_payload.get("messages")
    if isinstance(messages, list):
        payload["messages"] = [str(message) for message in messages if message]

    return payload


def get_outline_from_db(
    session: Session,
    document_id: int,
    *,
    settings: Settings,
    document: Optional[Document] = None,
) -> Optional[dict[str, Any]]:
    """Return the persisted outline payload for ``document_id``."""

    record = get_headers_from_db(
        session,
        document_id,
        settings=settings,
        document=document,
    )
    if record is None:
        return None

    return {
        "documentId": record["documentId"],
        "runId": record["runId"],
        "outline": record.get("outline"),
        "meta": record.get("meta"),
    }


@router.post("/headers/{document_id}")
async def compute_headers(
    document_id: int,
    *,
    trace: bool = Query(False, description="Return inline trace events when available"),
    align: str | None = Query(
        None,
        description="Header alignment strategy (sequential, legacy).",
    ),
    force: bool = Query(
        False,
        description="Force new LLM headers; purge prior headers/sections and bypass caches.",
    ),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Return LLM-provided headers and alignment matches for ``document_id``."""

    return await extract_headers_and_chunks(
        document_id=document_id,
        settings=settings,
        session=session,
        force=force,
        trace=trace,
        align=align,
    )


async def extract_headers_and_chunks(
    *,
    document_id: int,
    settings: Settings,
    session: Session,
    force: bool = False,
    trace: bool = False,
    align: str | None = None,
) -> Dict[str, Any] | JSONResponse:
    """Core header extraction workflow shared by routers and tests."""

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

    doc_id = int(document.id)

    if not force:
        cached_payload = get_headers_from_db(
            session,
            doc_id,
            settings=settings,
            document=document,
        )
        if cached_payload is not None:
            return cached_payload

    if force:
        try:
            delete_sections_for_document(session=session, document_id=doc_id)
        except Exception:
            # Deletion failures should not block a re-run.
            pass
        SimpleHeadersState.clear(doc_id)

    provider = settings.llm_provider.lower()
    api_key_present = bool((settings.openrouter_api_key or "").strip())
    use_simple_llm = (
        settings.headers_mode.lower() == "llm_simple"
        and not force
        and provider != "disabled"
        and api_key_present
    )
    if use_simple_llm:
        try:
            llm_obj = await get_headers_llm_json(document_id, session, settings)
        except InvalidLLMJSONError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid_llm_json"},
            )

        matches = find_header_occurrences(
            session, document_id, llm_obj.get("headers", [])
        )
        return {"llm_headers": llm_obj.get("headers", []), "matches": matches}

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
    parse_result, _ = get_or_create_parse_result(
        session=session,
        document=document,
        document_path=document_path,
        settings=settings,
        parse_func=parse_impl,
    )

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
    orchestrator_impl = orchestrate_headers_and_chunks
    if headers_router is not None:
        orchestrator_impl = getattr(
            headers_router, "extract_headers_and_chunks", orchestrate_headers_and_chunks
        )

    orchestrator_kwargs: Dict[str, Any] = {
        "settings": settings,
        "native_headers": native_headers,
        "metadata": {
            "filename": document.filename,
            "document_id": doc_id,
        },
        "session": session,
        "document": document,
        "want_trace": trace,
        "force": force,
        "align": align,
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

    llm_headers = list(orchestrated.get("llm_headers", []))

    persisted_sections = build_and_store_sections(
        session=session,
        document_id=doc_id,
        simpleheaders=orchestrated.get("headers", []),
        lines=lines,
    )
    section_key_by_gid = {
        int(section.start_global_idx): section.section_key for section in persisted_sections
    }

    simpleheaders_source = orchestrated.get("headers", []) or []
    simpleheaders_payload = _serialise_simpleheaders(
        simpleheaders_source,
        section_key_by_gid,
    )

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

    try:
        persist_sections(
            document_id=str(doc_id),
            filename=document.filename,
            sections=sections_payload,
            headers=simpleheaders_payload,
        )
    except Exception:  # pragma: no cover - persistence should not block response
        pass

    outline_payload = header_result.to_json()
    if llm_headers:
        outline_nodes = build_outline_from_simpleheaders(llm_headers)
        outline_payload = [node.to_dict() for node in outline_nodes]

    if trace and tracer is not None:
        trace_payload = {
            "events": tracer.as_list(),
            "path": tracer.path,
            "summary_path": tracer.summary_path,
        }
    else:
        trace_payload = None

    db_payload = get_headers_from_db(
        session,
        doc_id,
        settings=settings,
        document=document,
    )

    if db_payload is None:
        db_payload = {
            "documentId": doc_id,
            "runId": None,
            "outline": outline_payload,
            "meta": {
                "model": settings.headers_llm_model,
                "promptHash": None,
                "sourceHash": doc_hash or None,
                "tokens": {"prompt": None, "completion": None},
                "latencyMs": orchestrated.get("latency_ms"),
                "createdAt": None,
            },
            "sections": sections_payload,
            "simpleheaders": simpleheaders_payload,
        }
        if doc_hash:
            db_payload["docHash"] = doc_hash
        mode = orchestrated.get("mode")
        if mode:
            db_payload["mode"] = mode
        fallback_messages = list(header_result.messages) + list(
            orchestrated.get("messages", [])
        )
        if fallback_messages:
            db_payload["messages"] = fallback_messages

    if trace_payload is not None:
        db_payload["trace"] = trace_payload

    return db_payload


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


__all__ = ["router", "extract_headers_and_chunks"]
