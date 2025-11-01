"""Utilities for aligning LLM-reported headers with parsed lines."""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List

from ..config import get_settings
from .lines import Line, iter_lines

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

    matches: List[Dict] = []
    log_path = settings.headers_log_dir / f"header_matches_{document_id}.jsonl"

    with log_path.open("w", encoding="utf-8") as handle:
        for header in llm_headers or []:
            title = str(header.get("title", ""))
            try:
                level = int(header.get("level", 1))
            except (TypeError, ValueError):
                level = 1
            try:
                expected_page = int(header.get("page", 0))
            except (TypeError, ValueError):
                expected_page = 0

            match = _find_match(lines, normalised, title, expected_page)
            result = {
                "llm_title": title,
                "level": level,
                "expected_page": expected_page,
                "found": match is not None,
                "found_page": int(match["page"]) if match else None,
                "line_in_page": int(match["line_in_page"]) if match else None,
                "matched_text": str(match["text"]) if match else None,
            }

            matches.append(result)
            handle.write(json.dumps(result, ensure_ascii=False))
            handle.write("\n")

    return matches


__all__ = ["find_header_occurrences"]
