"""Utility helpers for rough token counting and chunking."""

from __future__ import annotations

import math
from typing import Iterable, List


def rough_token_count(text: str) -> int:
    """Return a rough token count using a conservative 4 char/token estimate."""

    if not text:
        return 1
    return max(1, math.ceil(len(text) / 4))


def split_by_token_limit(blocks: Iterable[str], limit_tokens: int) -> List[str]:
    """Split a sequence of text blocks into groups under the token limit."""

    if limit_tokens <= 0:
        raise ValueError("limit_tokens must be a positive integer")

    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for block in blocks:
        text = block or ""
        tokens = rough_token_count(text)
        if current and current_tokens + tokens > limit_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(text)
        current_tokens += tokens

    if current:
        groups.append(current)

    return ["\n".join(group) for group in groups]


__all__ = ["rough_token_count", "split_by_token_limit"]
