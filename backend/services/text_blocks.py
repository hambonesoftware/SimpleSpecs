"""Utilities for working with parsed text blocks."""
from __future__ import annotations

import difflib
import re
from typing import Sequence

from ..models import HeaderItem, ParsedObject


def document_lines(objects: Sequence[dict | ParsedObject]) -> list[str]:
    """Return a list of text lines extracted from parsed objects."""

    lines: list[str] = []
    for obj in objects:
        data = obj
        if isinstance(obj, ParsedObject):
            data = obj.model_dump()
        kind = data.get("kind") or data.get("type")
        text = data.get("text") or data.get("content") or ""
        if kind == "text":
            content = str(text).strip()
            if content:
                lines.append(content)
        elif kind == "table":
            content = str(text).strip()
            if content:
                lines.extend(line.strip() for line in content.splitlines() if line.strip())
    return lines


def document_text(objects: Sequence[dict | ParsedObject]) -> str:
    return "\n".join(document_lines(objects))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


def _find_line_index(lines: Sequence[str], header: HeaderItem) -> int:
    target_combo = _normalize(f"{header.section_number} {header.section_name}")
    target_number = _normalize(header.section_number)
    target_name = _normalize(header.section_name)

    for idx, line in enumerate(lines):
        normalized = _normalize(line)
        if normalized.startswith(target_combo):
            return idx
    for idx, line in enumerate(lines):
        normalized = _normalize(line)
        if target_number and normalized.startswith(target_number):
            if target_name in normalized:
                return idx
    for idx, line in enumerate(lines):
        normalized = _normalize(line)
        if target_name and target_name in normalized:
            return idx

    if lines:
        match = difflib.get_close_matches(header.section_name, lines, n=1, cutoff=0.0)
        if match:
            return lines.index(match[0])
    return 0


def section_text(lines: Sequence[str], headers: Sequence[HeaderItem], header: HeaderItem) -> str:
    """Return the best-effort text for a header section."""

    if not lines:
        return ""

    start_index = _find_line_index(lines, header)
    try:
        position = next(
            index
            for index, candidate in enumerate(headers)
            if candidate.section_number == header.section_number
            and candidate.section_name == header.section_name
        )
    except StopIteration:
        position = 0
    subsequent_headers = headers[position + 1 :]
    next_index = len(lines)
    for candidate in subsequent_headers:
        candidate_index = _find_line_index(lines, candidate)
        if candidate_index > start_index and candidate_index < next_index:
            next_index = candidate_index
    if next_index <= start_index:
        next_index = len(lines)

    extracted = lines[start_index:next_index]
    return "\n".join(extracted).strip()
