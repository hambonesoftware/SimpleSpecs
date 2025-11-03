"""In-memory cache for simple header line metrics."""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Tuple


class SimpleHeadersState:
    """Store recently computed line metrics for section retrieval."""

    _max_entries = 6
    _store: "OrderedDict[int, Tuple[str, list[dict]]]" = OrderedDict()

    @classmethod
    def set(cls, document_id: int, doc_hash: str, lines: Iterable[dict]) -> None:
        cls._store.pop(document_id, None)
        cls._store[document_id] = (doc_hash, list(lines))
        while len(cls._store) > cls._max_entries:
            cls._store.popitem(last=False)

    @classmethod
    def get(cls, document_id: int) -> tuple[str, list[dict]] | None:
        value = cls._store.get(document_id)
        if value is None:
            return None
        cls._store.move_to_end(document_id)
        return value


    @classmethod
    def clear(cls, document_id: int | None = None) -> None:
        """Remove cached state for ``document_id`` or clear all entries."""

        if document_id is None:
            cls._store.clear()
            return

        cls._store.pop(document_id, None)


__all__ = ["SimpleHeadersState"]
