"""Locate LLM derived headers within parsed line metrics."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Sequence


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def locate_headers_in_lines(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    excluded_pages: Iterable[int] = (),
    similarity_threshold: float = 0.88,
) -> List[Dict]:
    """Return located headers with page and line metadata."""

    excluded = set(excluded_pages)
    usable: list[dict] = []
    for line in lines:
        if line.get("page") in excluded:
            continue
        if line.get("is_running"):
            continue
        copy = dict(line)
        copy["_norm"] = _normalise(str(line.get("text", "")))
        usable.append(copy)

    located: list[Dict] = []

    for header in headers:
        target = _normalise(str(header.get("text", "")))
        if not target:
            continue
        number = (header.get("number") or "").strip()
        candidates: list[dict] = []

        for line in usable:
            text = str(line.get("text", ""))
            if number:
                if re.match(rf"^\s*{re.escape(number)}(?:\b|[.)\-\s])", text):
                    candidates.append(line)
                    continue
            norm = line.get("_norm", "")
            if norm == target or target in norm:
                candidates.append(line)

        if not candidates:
            for line in usable:
                norm = line.get("_norm", "")
                if not norm:
                    continue
                similarity = SequenceMatcher(a=target, b=norm).ratio()
                if similarity >= similarity_threshold:
                    candidates.append(line)

        if not candidates:
            continue

        best = max(candidates, key=lambda item: item.get("global_idx", -1))
        located.append(
            {
                "text": str(header.get("text", "")).strip(),
                "number": number or None,
                "level": int(header.get("level") or 1),
                "page": int(best.get("page") or 0),
                "line_idx": int(best.get("line_idx") or 0),
                "global_idx": int(best.get("global_idx") or 0),
            }
        )

    located.sort(key=lambda item: item.get("global_idx", 0))
    return located


__all__ = ["locate_headers_in_lines"]
