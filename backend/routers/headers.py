"""Endpoints for header extraction and outline delivery."""

from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
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
    flatten_outline,
)
from ..services.headers_llm_strict import extract_headers_and_sections_strict
from ..services.headers_orchestrator import extract_headers_and_chunks
from ..services.llm import LLMService
from ..services.pdf_native import collect_line_metrics, parse_pdf
from ..services.simpleheaders_state import SimpleHeadersState

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


class SimpleHeaderPayload(BaseModel):
    """Flat header entry mapped to precise line indices."""

    text: str
    number: str | None = None
    level: int
    page: int
    line_idx: int
    global_idx: int


class SectionPayload(BaseModel):
    """Chunk describing the line range belonging to a header."""

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

    if settings.headers_llm_strict:
        llm_service = LLMService(settings)
        if llm_service.is_enabled:
            lines, _, doc_hash = collect_line_metrics(
                document_bytes,
                {"filename": document.filename},
                suppress_toc=settings.headers_suppress_toc,
                suppress_running=settings.headers_suppress_running,
            )
            strict_output = extract_headers_and_sections_strict(
                llm=llm_service,
                lines=lines,
            )

            SimpleHeadersState.set(doc_id, doc_hash, lines)

            simpleheaders_payload = [
                SimpleHeaderPayload(
                    text=item.get("text", ""),
                    number=item.get("number"),
                    level=int(item.get("level", 1)),
                    page=int(item.get("start_page", 0)),
                    line_idx=int(item.get("line_index", 0)),
                    global_idx=int(item.get("start_global_index", 0)),
                )
                for item in strict_output.get("headers", [])
            ]

            sections_payload = [
                SectionPayload(
                    header_text=section.get("text", ""),
                    header_number=section.get("number"),
                    level=int(section.get("level", 1)),
                    start_global_idx=int(section.get("start_global_index", 0)),
                    end_global_idx=int(
                        section.get(
                            "end_global_index", section.get("start_global_index", 0)
                        )
                    ),
                    start_page=int(section.get("start_page", 0)),
                    end_page=int(
                        section.get("end_page", section.get("start_page", 0))
                    ),
                )
                for section in strict_output.get("sections", [])
            ]

            return HeadersResponse(
                document_id=doc_id,
                source="llm_strict",
                fenced_text=strict_output.get("fenced_text", ""),
                outline=[],
                simpleheaders=simpleheaders_payload,
                sections=sections_payload,
                mode="llm_strict",
            )

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

    orchestrated = await extract_headers_and_chunks(
        document_bytes,
        **orchestrator_kwargs,
    )

    SimpleHeadersState.set(doc_id, orchestrated["doc_hash"], orchestrated["lines"])

    simpleheaders_payload = [
        SimpleHeaderPayload(
            text=item.get("text", ""),
            number=item.get("number"),
            level=int(item.get("level", 1)),
            page=int(item.get("page", 0)),
            line_idx=int(item.get("line_idx", 0)),
            global_idx=int(item.get("global_idx", 0)),
        )
        for item in orchestrated.get("headers", [])
    ]

    sections_payload = [
        SectionPayload(
            header_text=section.get("header_text", ""),
            header_number=section.get("header_number"),
            level=int(section.get("level", 1)),
            start_global_idx=int(section.get("start_global_idx", 0)),
            end_global_idx=int(section.get("end_global_idx", 0)),
            start_page=int(section.get("start_page", 0)),
            end_page=int(section.get("end_page", 0)),
        )
        for section in orchestrated.get("sections", [])
    ]

    return HeadersResponse.from_result(
        doc_id,
        result,
        simpleheaders=simpleheaders_payload,
        sections=sections_payload,
        mode=orchestrated.get("mode"),
        messages=orchestrated.get("messages"),
    )


@router.get("/headers/{document_id}/section-text", response_class=PlainTextResponse)
async def section_text(
    document_id: int,
    start: int,
    end: int,
    *,
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    """Return the plain text for a section bounded by global indices."""

    if start < 0 or end < 0 or end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid section bounds",
        )

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    cached = SimpleHeadersState.get(document_id)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No section data available for this document",
        )

    _, lines = cached
    text_lines = [
        str(line.get("text", ""))
        for line in lines
        if start <= int(line.get("global_idx", -1)) <= end
    ]

    return PlainTextResponse("\n".join(text_lines))


__all__ = ["router"]
