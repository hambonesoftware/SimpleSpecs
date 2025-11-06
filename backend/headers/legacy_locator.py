"""Fallback header locator reused when the LLM fails."""

from __future__ import annotations

import re
from typing import List, Sequence

from .models import HeaderItem

_HEADER_RE = re.compile(
    r"^(?P<number>[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*)[\s:.-]+(?P<title>[^\d].*)$"
)


def _infer_level(number: str | None) -> int:
    if not number:
        return 1
    return min(6, number.count(".") + 1)


def legacy_outline(pages: Sequence[str]) -> List[HeaderItem]:
    """Return a coarse outline inferred directly from the text."""

    headers: List[HeaderItem] = []
    order = 0
    for page_index, page in enumerate(pages, start=1):
        for raw_line in str(page).splitlines():
            line = raw_line.strip()
            if len(line) < 4:
                continue
            match = _HEADER_RE.match(line)
            if not match:
                continue
            number = match.group("number")
            title = match.group("title").strip(" .-:")
            if not title:
                continue
            order += 1
            headers.append(
                HeaderItem(
                    number=number,
                    title=title,
                    level=_infer_level(number),
                    page=page_index,
                    order=order,
                    source="legacy",
                    meta={"legacy": True},
                )
            )
    return headers


__all__ = ["legacy_outline"]
