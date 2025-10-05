"""Shared helpers for header extraction endpoints."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, status

from ..config import get_settings
from ..logging import get_logger
from ..models import HeaderItem
from ..services.text_blocks import (
    document_line_entries,
    document_text,
    section_bounds,
    section_text,
)
from ..header_export import write_header_search_report
from ..store import headers_path, read_json, read_jsonl, upload_objects_path, write_json
from ..text.toc_filters import is_real_header_line, mark_toc_pages

logger = get_logger(__name__)

_HEADERS_PROMPT = """Please show a simple numbered nested list of all headers and subheaders for this document.
Return ONLY the list enclosed in #headers# fencing, like:

#headers#
1. Top Level
   1.1 Sub
      1.1.1 Sub-sub
2. Another Top
#headers#
"""

_HEADERS_BLOCK_RE = re.compile(r"#headers#(.*?)#headers#", re.DOTALL | re.IGNORECASE)
_SECTION_LINE_RE = re.compile(r"^(\d+(?:\.\d+)*)[\s\-\.]+(.+)$")


def _ingest_objects_path(upload_id: str) -> Path:
    settings = get_settings()
    return Path(settings.ARTIFACTS_DIR) / upload_id / "parsed" / "objects.json"


def _load_parsed_objects(upload_id: str) -> tuple[list[dict], bool]:
    """Return parsed objects for *upload_id* and whether any source was found."""

    source_found = False
    objects_raw: list[dict] = []

    jsonl_path = upload_objects_path(upload_id)
    if jsonl_path.exists():
        source_found = True
        objects_raw = read_jsonl(jsonl_path)

    if not objects_raw:
        ingest_path = _ingest_objects_path(upload_id)
        if ingest_path.exists():
            source_found = True
            data = read_json(ingest_path) or []
            if not isinstance(data, list):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Parsed objects file is malformed",
                )
            objects_raw = []
            for entry in data:
                if isinstance(entry, dict):
                    objects_raw.append(entry)
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Parsed objects entries must be mappings",
                    )

    return objects_raw, source_found


def fetch_document_text(upload_id: str) -> str:
    """Return the concatenated text for an uploaded document.

    Raises an ``HTTPException`` if the upload cannot be located or contains no text.
    """

    objects_raw, source_found = _load_parsed_objects(upload_id)
    if not source_found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    document = document_text(objects_raw)
    if not document.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is empty")
    return document


def build_header_messages(document: str) -> list[dict[str, str]]:
    """Construct chat messages for requesting headers from an LLM."""

    return [
        {"role": "system", "content": "You analyze engineering specification documents."},
        {"role": "user", "content": f"{_HEADERS_PROMPT}\n\nDocument contents:\n{document}"},
    ]


def _parse_headers_block(block: str) -> list[HeaderItem]:
    headers: list[HeaderItem] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _SECTION_LINE_RE.match(line)
        if not match:
            continue
        section_number = match.group(1).strip()
        section_name = match.group(2).strip()
        if section_number and section_name:
            headers.append(
                HeaderItem(section_number=section_number, section_name=section_name)
            )
    return headers


def persist_headers(upload_id: str, headers: Iterable[HeaderItem]) -> None:
    """Persist header items for future retrieval."""

    write_json(headers_path(upload_id), [header.model_dump() for header in headers])


def parse_and_store_headers(upload_id: str, response_text: str) -> list[HeaderItem]:
    """Extract ``HeaderItem`` entries from an LLM response and persist them."""

    logger.info("Raw header response: %s", response_text)

    match = _HEADERS_BLOCK_RE.search(response_text)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "LLM returned unexpected format",
                "response_text": response_text,
            },
        )

    headers = _parse_headers_block(match.group(1))
    if not headers:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No headers parsed",
        )

    objects_raw, _ = _load_parsed_objects(upload_id)
    entries = document_line_entries(objects_raw)
    toc_pages: set[int] = set()
    if entries:
        page_lines: dict[int, list[str]] = {}
        for entry in entries:
            if entry.page_index is None:
                continue
            page_lines.setdefault(entry.page_index, []).append(entry.text)
        if page_lines:
            max_page_index = max(page_lines)
            pages = [page_lines.get(i, []) for i in range(max_page_index + 1)]
            toc_pages = mark_toc_pages(pages)

        filtered_entries = [
            entry
            for entry in entries
            if is_real_header_line(
                entry.text,
                entry.page_index if entry.page_index is not None else -1,
                toc_pages,
            )
        ]
        if filtered_entries:
            entries = filtered_entries

    lines = [entry.text for entry in entries]

    for header in headers:
        if lines:
            start_index, _ = section_bounds(lines, headers, header)
            text = section_text(lines, headers, header)
        else:
            start_index = None
            text = ""
        normalized_text = text.strip() or f"{header.section_number} {header.section_name}".strip()
        header.chunk_text = normalized_text

        if (
            start_index is not None
            and 0 <= start_index < len(entries)
            and entries
        ):
            entry = entries[start_index]
            header.page_number = (
                entry.page_index + 1 if entry.page_index is not None else None
            )
            if entry.line_index is not None:
                header.line_number = entry.line_index + 1
            else:
                header.line_number = start_index + 1
        else:
            header.page_number = None
            header.line_number = None

    persist_headers(upload_id, headers)
    try:
        write_header_search_report(headers)
    except Exception:  # pragma: no cover - best effort logging
        logger.warning("Failed to write header search report", exc_info=True)
    return headers

__all__ = [
    "build_header_messages",
    "fetch_document_text",
    "parse_and_store_headers",
]
