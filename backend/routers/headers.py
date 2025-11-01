"""Endpoints for header extraction and outline delivery."""

from __future__ import annotations

import inspect
import os
import time

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

import backend.config as app_config
from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document, DocumentSection
from ..services.headers import (
    HeaderExtractionResult,
    HeaderNode,
    HeadersLLMClient,
    extract_headers,
    flatten_outline,
)
from ..services.headers_llm_strict import extract_headers_and_sections_strict
from ..services.headers_orchestrator import extract_headers_and_chunks
from ..services.llm import LLMService
from ..services.pdf_native import collect_line_metrics, parse_pdf
from ..services.sections import build_and_store_sections
from ..services.simpleheaders_state import SimpleHeadersState
from ..utils.trace import HeaderTracer

router = APIRouter(prefix="/api", tags=["headers"])


def _safe_int(value: object) -> int | None:
    """Return ``value`` coerced to ``int`` when possible."""

    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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


class SimpleHeaderPayload(BaseModel):
    """Flat header entry mapped to precise line indices."""

    text: str
    number: str | None = None
    level: int
    page: int
    line_idx: int
    global_idx: int
    section_key: str | None = None


class SectionPayload(BaseModel):
    """Chunk describing the line range belonging to a header."""

    section_key: str
    header_text: str
    header_number: str | None = None
    level: int
    start_global_idx: int
    end_global_idx: int
    start_page: int
    end_page: int


class HeadersResponse(BaseModel):
    """API response structure for header extraction."""

    document_id: int
    source: str
    fenced_text: str
    outline: list[HeaderNodePayload]
    simpleheaders: list[SimpleHeaderPayload] = Field(default_factory=list)
    sections: list[SectionPayload] = Field(default_factory=list)
    mode: str | None = None
    messages: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] | None = None
    trace_file: str | None = None

    @classmethod
    def from_result(
        cls,
        document_id: int,
        result: HeaderExtractionResult,
        *,
        simpleheaders: list[SimpleHeaderPayload] | None = None,
        sections: list[SectionPayload] | None = None,
        mode: str | None = None,
        messages: list[str] | None = None,
    ) -> "HeadersResponse":
        return cls(
            document_id=document_id,
            source=result.source,
            fenced_text=result.fenced_text,
            outline=[HeaderNodePayload.from_node(node) for node in result.outline],
            simpleheaders=simpleheaders or [],
            sections=sections or [],
            mode=mode,
            messages=[*result.messages, *(messages or [])],
        )


@router.post("/headers/{document_id}", response_model=HeadersResponse)
async def generate_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    trace: bool = Query(False),
    align: str | None = Query(None),
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

    document_bytes = document_path.read_bytes()

    trace_requested = trace or app_config.HEADERS_TRACE_EMBED_RESPONSE

    align_strategy = (align or "").strip().lower()
    if align_strategy in {"sequential", "legacy"}:
        os.environ["HEADERS_ALIGN_STRATEGY"] = align_strategy

    if settings.headers_llm_strict:
        llm_service = LLMService(settings)
        if llm_service.is_enabled:
            tracer: HeaderTracer | None = HeaderTracer(
                out_dir=app_config.HEADERS_TRACE_DIR
            )
            start_time = time.perf_counter()
            if tracer is not None:
                tracer.ev(
                    "start_run",
                    mode="llm_strict",
                    file_id=doc_id,
                    cfg={
                        "suppress_toc": settings.headers_suppress_toc,
                        "suppress_running": settings.headers_suppress_running,
                    },
                    metadata={"filename": document.filename},
                )

            lines, _, doc_hash = collect_line_metrics(
                document_bytes,
                {"filename": document.filename},
                suppress_toc=settings.headers_suppress_toc,
                suppress_running=settings.headers_suppress_running,
                tracer=tracer,
            )
            strict_output = extract_headers_and_sections_strict(
                llm=llm_service,
                lines=lines,
                tracer=tracer,
            )

            SimpleHeadersState.set(doc_id, doc_hash, lines)

            sections_models = build_and_store_sections(
                session=session,
                document_id=doc_id,
                simpleheaders=strict_output.get("headers", []),
                lines=lines,
            )
            key_by_anchor = {
                section.start_global_idx: section.section_key
                for section in sections_models
            }

            simpleheaders_payload: list[SimpleHeaderPayload] = []
            for item in strict_output.get("headers", []) or []:
                gid = _safe_int(
                    item.get("start_global_index") or item.get("global_idx")
                )
                resolved_gid = gid or 0
                simpleheaders_payload.append(
                    SimpleHeaderPayload(
                        text=item.get("text", ""),
                        number=item.get("number"),
                        level=int(item.get("level", 1)),
                        page=int(item.get("start_page", item.get("page", 0))),
                        line_idx=int(item.get("line_index", item.get("line_idx", 0))),
                        global_idx=int(resolved_gid),
                        section_key=key_by_anchor.get(resolved_gid),
                    )
                )

            sections_payload = []
            for section in sorted(
                sections_models, key=lambda entry: entry.start_global_idx
            ):
                end_bound = max(section.start_global_idx, section.end_global_idx - 1)
                sections_payload.append(
                    SectionPayload(
                        section_key=section.section_key,
                        header_text=section.title,
                        header_number=section.number,
                        level=section.level,
                        start_global_idx=section.start_global_idx,
                        end_global_idx=end_bound,
                        start_page=section.start_page or 0,
                        end_page=section.end_page or section.start_page or 0,
                    )
                )

            response = HeadersResponse(
                document_id=doc_id,
                source="llm_strict",
                fenced_text=strict_output.get("fenced_text", ""),
                outline=[],
                simpleheaders=simpleheaders_payload,
                sections=sections_payload,
                mode="llm_strict",
                trace=None,
                trace_file=None,
            )

            if tracer is not None:
                elapsed = time.perf_counter() - start_time
                tracer.ev(
                    "final_outline",
                    headers=[payload.model_dump() for payload in simpleheaders_payload],
                    sections=[section.model_dump() for section in sections_payload],
                    mode="llm_strict",
                    messages=[],
                    elapsed_s=elapsed,
                )
                tracer.ev(
                    "end_run",
                    elapsed_s=elapsed,
                    total_headers=len(simpleheaders_payload),
                    unresolved=[],
                    mode="llm_strict",
                    doc_hash=doc_hash,
                )
                tracer.flush_jsonl()
                if trace_requested:
                    response.trace = tracer.as_list()
                    response.trace_file = tracer.path

            return response

    parse_result = parse_pdf(document_path, settings=settings)
    llm_client = HeadersLLMClient(settings)
    result = extract_headers(parse_result, settings=settings, llm_client=llm_client)

    native_flat = flatten_outline(result.outline)
    orchestrator_kwargs = {
        "settings": settings,
        "native_headers": native_flat,
        "metadata": {"filename": document.filename},
    }

    signature = inspect.signature(extract_headers_and_chunks)
    if "session" in signature.parameters:
        orchestrator_kwargs["session"] = session
    if "document" in signature.parameters:
        orchestrator_kwargs["document"] = document

    orchestrated, tracer = await extract_headers_and_chunks(
        document_bytes,
        **orchestrator_kwargs,
        want_trace=trace_requested,
    )

    SimpleHeadersState.set(doc_id, orchestrated["doc_hash"], orchestrated["lines"])

    sections_models = build_and_store_sections(
        session=session,
        document_id=doc_id,
        simpleheaders=orchestrated.get("headers", []),
        lines=orchestrated.get("lines", []),
    )
    key_by_anchor = {
        section.start_global_idx: section.section_key for section in sections_models
    }

    simpleheaders_payload = []
    for item in orchestrated.get("headers", []) or []:
        gid = _safe_int(item.get("global_idx"))
        resolved_gid = gid or 0
        simpleheaders_payload.append(
            SimpleHeaderPayload(
                text=item.get("text", ""),
                number=item.get("number"),
                level=int(item.get("level", 1)),
                page=int(item.get("page", 0)),
                line_idx=int(item.get("line_idx", 0)),
                global_idx=int(resolved_gid),
                section_key=key_by_anchor.get(resolved_gid),
            )
        )

    sections_payload = []
    for section in sorted(sections_models, key=lambda entry: entry.start_global_idx):
        end_bound = max(section.start_global_idx, section.end_global_idx - 1)
        sections_payload.append(
            SectionPayload(
                section_key=section.section_key,
                header_text=section.title,
                header_number=section.number,
                level=section.level,
                start_global_idx=section.start_global_idx,
                end_global_idx=end_bound,
                start_page=section.start_page or 0,
                end_page=section.end_page or section.start_page or 0,
            )
        )

    response = HeadersResponse.from_result(
        doc_id,
        result,
        simpleheaders=simpleheaders_payload,
        sections=sections_payload,
        mode=orchestrated.get("mode"),
        messages=orchestrated.get("messages"),
    )

    if trace_requested and tracer is not None:
        response.trace = tracer.as_list()
        response.trace_file = tracer.path

    return response


@router.get("/headers/{document_id}/section-text", response_class=PlainTextResponse)
async def section_text(
    document_id: int,
    start: int,
    end: int,
    *,
    section_key: str | None = Query(None),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
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
