from __future__ import annotations

from backend.headers.chunk import make_chunks, stitch_chunks
from backend.headers.models import HeaderItem


def test_make_chunks_respects_token_budget() -> None:
    pages = [
        {"page": 1, "text": "one two three"},
        {"page": 2, "text": "four five six"},
        {"page": 3, "text": "seven eight nine"},
    ]
    chunks = make_chunks(pages, target_tokens=5)
    assert len(chunks) == 3
    assert [page.index for page in chunks[0]] == [1]
    assert [page.index for page in chunks[1]] == [2]
    assert [page.index for page in chunks[2]] == [3]


def test_stitch_chunks_deduplicates_and_preserves_order() -> None:
    chunk_a = [
        HeaderItem(number="1", title="Scope", level=1, page=1, order=0),
        HeaderItem(number="1.1", title="Purpose", level=2, page=1, order=1),
    ]
    chunk_b = [
        HeaderItem(number="1", title="Scope", level=1, page=1, order=0),
        HeaderItem(number="1.2", title="Applicability", level=2, page=2, order=2),
    ]
    stitched = stitch_chunks([chunk_a, chunk_b])
    titles = [item.title for item in stitched]
    assert titles == ["Scope", "Purpose", "Applicability"]
