"""Utility helpers for rough token counting and chunking."""

from __future__ import annotations

import math
from typing import Iterable, Iterator, List


def rough_token_count(text: str) -> int:
    """Return a rough token count using a conservative 4 char/token estimate."""

    if not text:
        return 1
    return max(1, math.ceil(len(text) / 4))


def _split_block(text: str, limit_tokens: int) -> Iterator[str]:
    """Yield sub-sections of *text* that respect the token limit."""

    if not text:
        yield ""
        return

    if rough_token_count(text) <= limit_tokens:
        yield text
        return

    # Use the inverse of ``rough_token_count`` to avoid overshooting the limit.
    char_limit = max(1, limit_tokens * 4)
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + char_limit, text_length)
        yield text[start:end]
        start = end


def split_by_token_limit(blocks: Iterable[str], limit_tokens: int) -> List[str]:
    """Split a sequence of text blocks into groups under the token limit."""

    if limit_tokens <= 0:
        raise ValueError("limit_tokens must be a positive integer")

    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for block in blocks:
        text = block or ""

        for segment in _split_block(text, limit_tokens):
            tokens = rough_token_count(segment)
            if current and current_tokens + tokens > limit_tokens:
                groups.append(current)
                current = []
                current_tokens = 0
            current.append(segment)
            current_tokens += tokens

    if current:
        groups.append(current)

    return ["\n".join(group) for group in groups]


__all__ = ["rough_token_count", "split_by_token_limit"]
