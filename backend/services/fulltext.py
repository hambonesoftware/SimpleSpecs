"""Helpers for rendering full document text from parsed line metrics."""

from __future__ import annotations

from typing import Iterable


def lines_to_fulltext(lines: Iterable[dict]) -> str:
    """Join lines into a newline-delimited string preserving order."""

    return "\n".join(str(line.get("text", "")) for line in lines)


__all__ = ["lines_to_fulltext"]
