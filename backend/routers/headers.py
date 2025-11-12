"""Compatibility router that delegates to :mod:`backend.api.headers`."""

from __future__ import annotations

import inspect
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlmodel import Session

from ..api import headers as headers_api
from ..config import Settings, get_settings
from ..database import get_session
from ..services.headers import HeadersLLMClient as HeadersLLMClientImpl
from ..services.headers_orchestrator import (
    extract_headers_and_chunks as orchestrator_extract_headers_and_chunks,
)
from ..services.pdf_native import parse_pdf as parse_pdf_impl

router = APIRouter(prefix="/api", tags=["headers"])


async def _call_extract_headers_and_chunks(
    *,
    document_id: int,
    session: Session,
    settings: Settings,
    force: bool,
    align: str | None,
) -> Any:
    """Call into ``backend.api.headers.extract_headers_and_chunks`` safely."""

    func = getattr(headers_api, "extract_headers_and_chunks", None)
    if not callable(func):
        raise HTTPException(status_code=500, detail="Header extraction unavailable")

    signature = inspect.signature(func)
    params = signature.parameters

    kwargs: Dict[str, Any] = {}

    if "document_id" in params:
        kwargs["document_id"] = document_id
    elif "doc_id" in params:
        kwargs["doc_id"] = document_id
    elif "id" in params:
        kwargs["id"] = document_id

    if "settings" in params:
        kwargs["settings"] = settings
    if "session" in params:
        kwargs["session"] = session
    if "force" in params:
        kwargs["force"] = force
    if "align" in params:
        kwargs["align"] = align

    # Trace support is optional; only pass when accepted.
    if "trace" in params:
        kwargs.setdefault("trace", False)

    try:
        if not any(name in params for name in ("document_id", "doc_id", "id")):
            result = func(document_id, **kwargs)  # type: ignore[misc]
        else:
            result = func(**kwargs)
    except TypeError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Header extraction failed: {exc}") from exc

    if inspect.isawaitable(result):
        result = await result

    return result


@router.post("/headers/{document_id}")
async def compute_headers(
    document_id: int,
    *,
    force: bool = Query(
        False,
        description="Force new LLM headers; purge prior headers/sections and bypass caches.",
    ),
    align: str | None = Query(
        None,
        description="Header alignment strategy (sequential, legacy).",
    ),
    body: dict | None = Body(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Forward the request to :func:`backend.api.headers.extract_headers_and_chunks`."""

    effective_force = bool(force or (body or {}).get("force"))

    if effective_force:
        purge_cache = getattr(headers_api, "purge_llm_cache_for_document", None)
        if callable(purge_cache):
            try:
                purge_cache(document_id)
            except Exception:  # pragma: no cover - best-effort cleanup
                pass

    result = await _call_extract_headers_and_chunks(
        document_id=document_id,
        session=session,
        settings=settings,
        force=effective_force,
        align=align,
    )

    return result


@router.get("/headers/{document_id}")
def get_headers(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Return the persisted headers payload for ``document_id``."""

    payload = headers_api.get_headers_from_db(
        session,
        document_id,
        settings=settings,
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Headers not found",
        )
    return payload


@router.get("/headers/{document_id}/outline")
def get_headers_outline(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Return the persisted raw outline for ``document_id``."""

    payload = headers_api.get_outline_from_db(
        session,
        document_id,
        settings=settings,
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outline not found",
        )
    return payload


parse_pdf = parse_pdf_impl
extract_headers_and_chunks = orchestrator_extract_headers_and_chunks


@router.get("/headers/{document_id}/section-text", response_class=PlainTextResponse)
def section_text(
    document_id: int,
    start: int,
    end: int,
    *,
    section_key: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Compatibility shim for :func:`backend.api.headers.section_text`."""

    return headers_api.section_text(
        document_id=document_id,
        start=start,
        end=end,
        section_key=section_key,
        session=session,
    )
HeadersLLMClient = HeadersLLMClientImpl

__all__ = [
    "router",
    "compute_headers",
    "parse_pdf",
    "extract_headers_and_chunks",
    "section_text",
    "HeadersLLMClient",
]

