"""Normalization utilities applied before sequential alignment."""

from __future__ import annotations

import re
from typing import List, Sequence

from .models import HeaderItem

_CONFUSABLE_DIGITS = str.maketrans(
    {
        "Ⅰ": "1",
        "Ⅱ": "2",
        "Ⅲ": "3",
        "Ⅳ": "4",
        "Ⅴ": "5",
        "Ⅵ": "6",
        "Ⅶ": "7",
        "Ⅷ": "8",
        "Ⅸ": "9",
        "Ⅹ": "10",
        "I": "1",
        "l": "1",
        "|": "1",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_SEP_RE = re.compile(r"[\s\-–—]+")
_NON_DIGIT_RE = re.compile(r"[^0-9A-Za-z.]+")
_DOT_RUN_RE = re.compile(r"\.+")


def normalize_number(value: str | None, *, confusables: bool = True) -> str | None:
    """Return a canonical dotted number representation."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if confusables:
        text = text.translate(_CONFUSABLE_DIGITS)
    text = text.replace("·", ".")
    text = _SEP_RE.sub(".", text)
    text = _NON_DIGIT_RE.sub(".", text)
    text = _DOT_RUN_RE.sub(".", text)
    text = text.strip(".")
    return text or None


def normalize_title(value: str, *, confusables: bool = True) -> str:
    """Return a whitespace-normalised heading title."""

    text = _WHITESPACE_RE.sub(" ", value or "").strip()
    return text


def normalize_headers(
    headers: Sequence[HeaderItem],
    *,
    suppress_toc: bool = True,
    suppress_running: bool = True,
    normalize_confusables: bool = True,
) -> List[HeaderItem]:
    """Return a filtered, deduplicated list of headers."""

    seen: set[tuple[str | None, str]] = set()
    cleaned: List[HeaderItem] = []

    for item in headers:
        if suppress_toc and item.meta.get("toc"):
            continue
        if suppress_running and item.meta.get("running"):
            continue
        number = normalize_number(item.number, confusables=normalize_confusables)
        title = normalize_title(item.title, confusables=normalize_confusables)
        signature = (number, title.casefold())
        if signature in seen:
            continue
        seen.add(signature)
        cleaned.append(
            HeaderItem(
                number=number,
                title=title,
                level=max(1, int(item.level or 1)),
                page=item.page,
                order=item.order,
                source=item.source,
                meta=dict(item.meta),
            )
        )
    return cleaned


__all__ = ["normalize_number", "normalize_title", "normalize_headers"]
