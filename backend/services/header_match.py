"""Utilities for aligning LLM-reported headers with parsed lines."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

from ..config import get_settings
from .lines import Line, iter_lines
from .headers_llm_strict import align_headers_llm_strict
from .headers_sequential import extract_number

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Collapse whitespace and lower-case ``text`` for fuzzy comparisons."""

    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def _find_match(
    lines: Iterable[Line],
    normalised: List[tuple[str, Line]],
    title: str,
    expected_page: int,
) -> Line | None:
    if not title:
        return None

    def _iter_lines(prefer_page: bool) -> Iterable[Line]:
        for line in lines:
            if prefer_page and expected_page and int(line["page"]) != expected_page:
                continue
            yield line

    for line in _iter_lines(prefer_page=True):
        if title in str(line["text"]):
            return line
    for line in _iter_lines(prefer_page=False):
        if title in str(line["text"]):
            return line

    target = _normalise(title)
    if not target:
        return None

    def _iter_normalised(prefer_page: bool) -> Iterable[tuple[str, Line]]:
        for value, line in normalised:
            if prefer_page and expected_page and int(line["page"]) != expected_page:
                continue
            yield value, line

    for value, line in _iter_normalised(prefer_page=True):
        if value == target:
            return line
    for value, line in _iter_normalised(prefer_page=False):
        if value == target:
            return line

    return None


def _prepare_strict_lines(lines: Iterable[Line]) -> List[Dict[str, Any]]:
    """Return line dictionaries compatible with the strict header locator."""

    prepared: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        text = str(line.get("text", ""))
        try:
            page = int(line.get("page", 0))
        except (TypeError, ValueError):
            page = 0
        try:
            line_in_page = int(line.get("line_in_page", 0))
        except (TypeError, ValueError):
            line_in_page = 0
        prepared.append(
            {
                "text": text,
                "page": page,
                "line_in_page": line_in_page,
                "global_idx": idx,
                "line_idx": idx,
                "is_toc": False,
                "is_index": False,
                "is_running": False,
            }
        )
    return prepared


def _prepare_strict_headers(
    llm_headers: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Coerce LLM headers into dictionaries understood by the strict locator."""

    strict_headers: List[Dict[str, Any]] = []
    for idx, header in enumerate(llm_headers):
        title = str(header.get("title", "")).strip()
        if not title:
            continue
        try:
            level = int(header.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        number = header.get("number")
        if isinstance(number, str):
            number = number.strip() or None
        else:
            number = None
        if number is None:
            number = extract_number(title)
        strict_headers.append(
            {
                "text": title,
                "number": number,
                "level": level,
                "_orig_index": idx,
            }
        )
    return strict_headers


def find_header_occurrences(
    session,
    document_id: int,
    llm_headers: List[Dict],
) -> List[Dict]:
    """Match LLM headers to parsed lines and emit a JSONL log."""

    settings = get_settings()
    settings.headers_log_dir.mkdir(parents=True, exist_ok=True)

    lines = list(iter_lines(session, document_id))
    normalised = [(_normalise(str(line["text"])), line) for line in lines]

    strict_mode = settings.headers_llm_strict
    strict_lines = _prepare_strict_lines(lines) if strict_mode else []
    strict_headers = _prepare_strict_headers(llm_headers or []) if strict_mode else []
    resolved_by_index: Dict[int, Dict[str, Any]] = {}

    if strict_mode and strict_lines and any(
        header.get("text") for header in strict_headers
    ):
        resolved = align_headers_llm_strict(strict_headers, strict_lines, tracer=None)
        for item in resolved:
            header = item.get("header", {})
            orig_index = header.get("_orig_index")
            if isinstance(orig_index, int):
                resolved_by_index[orig_index] = item

    matches: List[Dict] = []
    log_path = settings.headers_log_dir / f"header_matches_{document_id}.jsonl"

    with log_path.open("w", encoding="utf-8") as handle:
        for index, header in enumerate(llm_headers or []):
            title = str(header.get("title", ""))
            try:
                level = int(header.get("level", 1))
            except (TypeError, ValueError):
                level = 1
            try:
                expected_page = int(header.get("page", 0))
            except (TypeError, ValueError):
                expected_page = 0

            strict_match = resolved_by_index.get(index)
            match_line: Dict[str, Any] | None = None
            if strict_match is not None:
                match_line = strict_match.get("line")
            if match_line is None:
                match_line = _find_match(lines, normalised, title, expected_page)

            result = {
                "llm_title": title,
                "level": level,
                "expected_page": expected_page,
                "found": match_line is not None,
                "found_page": int(match_line.get("page", 0)) if match_line else None,
                "line_in_page": (
                    int(match_line.get("line_in_page", 0)) if match_line else None
                ),
                "matched_text": str(match_line.get("text", "")) if match_line else None,
            }

            matches.append(result)
            handle.write(json.dumps(result, ensure_ascii=False))
            handle.write("\n")

    return matches


__all__ = ["find_header_occurrences"]
