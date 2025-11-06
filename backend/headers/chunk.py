"""Chunk helpers for the headers extractor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Sequence

from .models import HeaderItem
from .normalize import normalize_number, normalize_title


@dataclass(frozen=True)
class ChunkPage:
    """Minimal representation of a page for chunking."""

    index: int
    text: str
    tokens: int


def _approximate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def make_chunks(pages: Sequence[Mapping[str, object] | str], target_tokens: int) -> List[List[ChunkPage]]:
    """Split *pages* into token-aware chunks."""

    chunks: List[List[ChunkPage]] = []
    current: List[ChunkPage] = []
    budget = max(1, int(target_tokens))
    tokens_used = 0

    for raw_index, page in enumerate(pages, start=1):
        if isinstance(page, Mapping):
            text = str(page.get("text", ""))
            page_no = int(page.get("page", raw_index) or raw_index)
        else:
            text = str(page)
            page_no = raw_index
        page_tokens = _approximate_tokens(text)
        payload = ChunkPage(index=page_no, text=text, tokens=page_tokens)
        if current and tokens_used + page_tokens > budget:
            chunks.append(current)
            current = []
            tokens_used = 0
        current.append(payload)
        tokens_used += page_tokens
    if current:
        chunks.append(current)
    return chunks or [[]]


def stitch_chunks(chunk_headers: Iterable[Iterable[HeaderItem]]) -> List[HeaderItem]:
    """Return a stable, deduplicated list of headers from chunk outputs."""

    stitched: List[HeaderItem] = []
    seen: set[tuple[str | None, str]] = set()
    for group in chunk_headers:
        for item in group:
            number = normalize_number(item.number)
            title = normalize_title(item.title)
            key = (number, title.casefold())
            if key in seen:
                continue
            seen.add(key)
            stitched.append(
                HeaderItem(
                    number=number,
                    title=title,
                    level=item.level,
                    page=item.page,
                    order=item.order,
                    source=item.source,
                    meta=dict(item.meta),
                )
            )
    return stitched


__all__ = ["ChunkPage", "make_chunks", "stitch_chunks"]
