"""Validation utilities for SIMPLEHEADERS responses."""

from __future__ import annotations

import json
import re
from typing import Any, List

from .models import HeaderItem

_FENCE_RE = re.compile(r"```SIMPLEHEADERS\s*(?:\r?\n)(.*?)(?:\r?\n)?```", re.DOTALL)
_ANY_FENCE_RE = re.compile(r"```([A-Za-z0-9_-]+)")


def extract_fenced_simpleheaders_block(text: str) -> str | None:
    """Return the JSON payload inside a single SIMPLEHEADERS fence.

    Returns ``None`` when no fence (or more than one fence) is present.
    """

    if text is None:
        return None
    matches = _FENCE_RE.findall(text)
    if len(matches) != 1:
        return None
    payload = matches[0].strip()
    return payload or None


def detect_bad_label(text: str) -> bool:
    """Return ``True`` when a fenced block exists but is not SIMPLEHEADERS."""

    if text is None:
        return False
    for match in _ANY_FENCE_RE.finditer(text):
        label = match.group(1)
        if label.upper() != "SIMPLEHEADERS":
            return True
    return False


def _coerce_number(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_page(value: Any) -> int | None:
    if value in {None, "", "null"}:
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_json") from None
    return page if page >= 0 else None


def _coerce_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_json") from None
    return max(1, level)


def validate_headers_json(obj: Any) -> List[HeaderItem]:
    """Validate *obj* against the SIMPLEHEADERS schema."""

    if not isinstance(obj, list):
        raise ValueError("invalid_json")

    cleaned: List[HeaderItem] = []
    for index, entry in enumerate(obj):
        if not isinstance(entry, dict):
            raise ValueError("invalid_json")
        title = entry.get("title") or entry.get("text")
        if not isinstance(title, str):
            raise ValueError("invalid_json")
        title_clean = title.strip()
        if not title_clean:
            raise ValueError("invalid_json")
        number = _coerce_number(entry.get("number"))
        level = _coerce_level(entry.get("level", 1))
        page = _coerce_page(entry.get("page"))
        cleaned.append(
            HeaderItem(
                number=number,
                title=title_clean,
                level=level,
                page=page,
                order=index,
            )
        )
    return cleaned


def parse_fenced_payload(text: str) -> List[HeaderItem]:
    """Extract and validate the SIMPLEHEADERS block from *text*."""

    block = extract_fenced_simpleheaders_block(text)
    if block is None:
        raise ValueError("missing_fence")
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:  # pragma: no cover - handled in tests
        raise ValueError("invalid_json") from exc
    return validate_headers_json(payload)


__all__ = [
    "detect_bad_label",
    "extract_fenced_simpleheaders_block",
    "validate_headers_json",
    "parse_fenced_payload",
]
