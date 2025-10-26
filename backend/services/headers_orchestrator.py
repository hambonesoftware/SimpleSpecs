"""Coordinator for LLM-backed and native header extraction flows."""

from __future__ import annotations

import logging
from typing import Mapping, Sequence

from backend.config import Settings

from .header_locator import locate_headers_in_lines
from .pdf_headers_llm_full import get_headers_llm_full
from .pdf_native import collect_line_metrics
from .section_chunking import single_chunks_from_headers

LOGGER = logging.getLogger(__name__)


async def extract_headers_and_chunks(
    document_bytes: bytes,
    *,
    settings: Settings,
    native_headers: Sequence[Mapping[str, object]] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> dict:
    """Return located headers and section ranges for the provided document."""

    lines, excluded_pages, doc_hash = collect_line_metrics(
        document_bytes,
        metadata,
        suppress_toc=settings.headers_suppress_toc,
        suppress_running=settings.headers_suppress_running,
    )

    located_headers: list[dict] = []
    mode_used = "native"

    if settings.headers_mode.lower() == "llm_full":
        try:
            llm_headers = await get_headers_llm_full(
                lines,
                doc_hash,
                settings=settings,
                excluded_pages=excluded_pages,
            )
            located_headers = locate_headers_in_lines(
                llm_headers,
                lines,
                excluded_pages=excluded_pages,
            )
            if located_headers:
                mode_used = "llm_full"
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            LOGGER.warning("LLM header extraction failed: %s", exc)
            located_headers = []

    if not located_headers and native_headers:
        located_headers = locate_headers_in_lines(
            native_headers,
            lines,
            excluded_pages=excluded_pages,
        )
        mode_used = "native"

    sections = single_chunks_from_headers(located_headers, lines)

    return {
        "headers": located_headers,
        "sections": sections,
        "mode": mode_used,
        "lines": lines,
        "doc_hash": doc_hash,
        "excluded_pages": sorted(excluded_pages),
    }


__all__ = ["extract_headers_and_chunks"]
