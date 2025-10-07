"""Shared helpers for header extraction endpoints."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Optional

from fastapi import HTTPException, status

from ..config import get_settings
from ..header_export import write_header_search_report
from ..logging import get_logger
from ..models import HeaderItem
from ..services.text_blocks import (
    document_line_entries,
    document_text,
    section_bounds,
    section_text,
)
from ..store import headers_path, read_json, read_jsonl, upload_objects_path, write_json
from ..text.toc_filters import is_real_header_line, mark_toc_pages

logger = get_logger(__name__)

_DOT_LEADER_RE = re.compile(r"\.{2,}")
_PAGE_NUM_AT_END_RE = re.compile(r"\s+(\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_ROMAN_RE = re.compile(r"^\s*[ivxlcdm]+\s*$", re.IGNORECASE)
_TOCY_LINE = re.compile(r"\.{2,}\s*(\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)

_HEADERS_PROMPT = """Please show a simple numbered nested list of all headers and subheaders for this document.
Return ONLY the list enclosed in #headers# fencing, like:

#headers#
1. Top Level
   1.1 Sub
      1.1.1 Sub-sub
2. Another Top
#headers#

Rules:
- Never read from the table of contents or index. Only capture section titles in the body.
- Ignore any line that contains dot leaders (e.g., "......") or ends with a page number.
- If a heading appears both in a TOC and in the body, keep the body occurrence only.
- Close the list with "#headers#" and terminate output immediately afterwards.
"""

_HEADERS_BLOCK_RE = re.compile(
    r"#headers#(.*?)(?:#headers#|#headers_end#)", re.DOTALL | re.IGNORECASE
)
_SECTION_LINE_RE = re.compile(r"^(\d+(?:\.\d+)*)[\s\-\.]+(.+)$")
_TITLE_LENGTH_LIMIT = 120


def _fix_ocr_artifacts(text: str) -> str:
    """Normalize common OCR quirks that confuse downstream heuristics."""

    cleaned = re.sub(r"(\w)-\n(\w)", r"\1-\2", text)
    cleaned = re.sub(r"(\w)-\n([a-z])", r"\1\2", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


def _drop_repeated_headers_and_footers(lines: list[str], max_unique: int = 8) -> list[str]:
    """Remove lines that repeat across many pages (likely headers/footers)."""

    counter = Counter(s.strip() for s in lines if s.strip())
    threshold = max(len(lines) // max_unique, 10)
    banned = {line for line, count in counter.items() if count > threshold}
    return [line for line in lines if line.strip() not in banned]


def _find_toc_window(lines: list[str]) -> tuple[int, int]:
    """Identify a table-of-contents block inside ``lines``."""

    start = -1
    for idx, line in enumerate(lines[:300]):
        lowered = line.strip().lower()
        if lowered in {"contents", "table of contents"}:
            start = idx
            break
    if start == -1:
        return -1, -1

    end = start + 1
    seen_entries = 0
    while end < len(lines):
        raw = lines[end].rstrip()
        if not raw.strip():
            end += 1
            continue

        toc_like = bool(_DOT_LEADER_RE.search(raw) and _PAGE_NUM_AT_END_RE.search(raw))
        if toc_like:
            seen_entries += 1
            end += 1
            continue

        looks_like_header = bool(
            re.match(r"^\s*(Appendix\s+[A-Z]|[A-Z]?\d+(?:\.\d+){0,4}\s+\S)", raw)
        )
        if seen_entries >= 3 and looks_like_header:
            break

        if seen_entries == 0:
            return -1, -1
        end += 1

    return start, end


def strip_frontmatter_and_toc(document: str) -> str:
    """Remove obvious front-matter, TOC pages, and OCR noise."""

    if not document:
        return document

    normalized = _fix_ocr_artifacts(document)
    lines = normalized.splitlines()
    lines = _drop_repeated_headers_and_footers(lines)

    trimmed: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if _ROMAN_RE.match(current.strip()):
            index += 1
            continue
        trimmed = lines[index:]
        break
    if trimmed:
        lines = trimmed

    start, end = _find_toc_window(lines)
    if start != -1:
        del lines[start:end]

    return "\n".join(lines).strip()


def clean_document_for_headers(document: str) -> str:
    """Return a cleaned version of *document* that is safer for prompting."""

    cleaned = strip_frontmatter_and_toc(document)
    return cleaned or document


def _window(text: str, idx: int, radius: int = 200) -> str:
    lo = max(0, idx - radius)
    hi = min(len(text), idx + radius)
    return text[lo:hi]


def locate_header_in_body(document: str, title: str) -> tuple[Optional[int], Optional[int]]:
    """Locate ``title`` inside ``document`` while rejecting TOC-like matches."""

    if not document or not title:
        return None, None

    pattern = re.sub(r"\s+", r"\\s+", re.escape(title.strip()))
    regex = re.compile(rf"(^|\n)\s*{pattern}\s*($|\n)", re.IGNORECASE)
    first_toc_match: Optional[int] = None

    match = regex.search(document)
    while match:
        line_start = document.rfind("\n", 0, match.end()) + 1
        line_end = document.find("\n", match.start())
        if line_end == -1:
            line_end = len(document)
        line = document[line_start:line_end]
        if _TOCY_LINE.search(line):
            if first_toc_match is None:
                first_toc_match = line_start
            match = regex.search(document, line_end + 1)
            continue
        return match.start(), first_toc_match

    segment = document[: min(len(document), 300_000)]
    best: tuple[float, int] | None = None
    title_lower = title.lower()
    for idx in range(0, max(1, len(segment) - len(title)), max(10, max(1, len(title) // 4))):
        window = segment[idx : idx + len(title) + 30]
        ratio = difflib.SequenceMatcher(None, title_lower, window.lower()).ratio()
        if ratio > 0.85 and (best is None or ratio > best[0]):
            best = (ratio, idx)

    if best:
        pos = best[1]
        line_start = document.rfind("\n", 0, pos) + 1
        line_end = document.find("\n", pos)
        if line_end == -1:
            line_end = len(document)
        line = document[line_start:line_end]
        if _TOCY_LINE.search(line):
            first_toc_match = first_toc_match or line_start
            return None, first_toc_match
        return pos, first_toc_match

    return None, first_toc_match


def verify_headers_against_document(
    document: str,
    headers: Iterable[HeaderItem],
    *,
    on_verify: Callable[[HeaderItem, int, str], None] | None = None,
    on_reject: Callable[[HeaderItem, Optional[str]], None] | None = None,
) -> list[HeaderItem]:
    """Filter ``headers`` to only those that appear in ``document``."""

    verified: list[HeaderItem] = []
    seen_titles: set[str] = set()

    for header in headers:
        title = (header.section_name or "").strip()
        if not title:
            continue
        if len(title) > _TITLE_LENGTH_LIMIT:
            if on_reject:
                on_reject(header, None)
            continue

        pos, toc_pos = locate_header_in_body(document, title)
        if pos is None and header.section_number:
            composite = f"{header.section_number} {title}".strip()
            pos, toc_pos = locate_header_in_body(document, composite)

        if pos is not None:
            key = title.lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            if on_verify:
                on_verify(header, pos, _window(document, pos))
            verified.append(header)
            continue

        snippet = _window(document, toc_pos) if toc_pos is not None else None
        if on_reject:
            on_reject(header, snippet)

    return verified


_HEADER_RULES = [
    re.compile(r"^\s*(Appendix\s+[A-Z]\b.*)$"),
    re.compile(r"^\s*([A-Z]?\d+(?:\.\d+){0,4}\s+[^\.\n]{1,120})\s*$"),
    re.compile(r"^\s*([A-Z][A-Z0-9][A-Z0-9 \-\(\)/,&]{3,80})\s*$"),
]


def rule_based_headers(document: str) -> list[HeaderItem]:
    """Deterministic fallback header extraction for ``document``."""

    results: list[HeaderItem] = []
    seen: set[str] = set()
    counter = 1

    for raw_line in document.splitlines():
        candidate = raw_line.strip()
        if not candidate or _TOCY_LINE.search(candidate):
            continue
        for pattern in _HEADER_RULES:
            match = pattern.match(candidate)
            if not match:
                continue
            title = match.group(1).strip()
            lowered = title.lower()
            if lowered in seen:
                break
            seen.add(lowered)

            section_number = None
            section_name = title
            structured = _SECTION_LINE_RE.match(title)
            if structured:
                section_number = structured.group(1).strip()
                section_name = structured.group(2).strip()
            else:
                section_number = str(counter)

            results.append(
                HeaderItem(section_number=section_number, section_name=section_name)
            )
            counter += 1
            break

    return results


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


def parse_and_store_headers(
    upload_id: str,
    response_text: str,
    *,
    cleaned_document: str | None = None,
    on_verify: Callable[[HeaderItem, int, str], None] | None = None,
    on_reject: Callable[[HeaderItem, Optional[str]], None] | None = None,
) -> list[HeaderItem]:
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

    if cleaned_document:
        verified = verify_headers_against_document(
            cleaned_document,
            headers,
            on_verify=on_verify,
            on_reject=on_reject,
        )
        if verified:
            headers = verified
        else:
            fallback = rule_based_headers(cleaned_document)
            if fallback:
                headers = fallback

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
    "clean_document_for_headers",
    "fetch_document_text",
    "parse_and_store_headers",
    "strip_frontmatter_and_toc",
]
