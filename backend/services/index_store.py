"""Lightweight vector index for hybrid RAG search."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..config import Settings, get_settings

__all__ = ["IndexItem", "IndexStore"]


@dataclass(slots=True)
class IndexItem:
    chunk_id: str
    text: str
    metadata: dict[str, object]


def _normalize_vector(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0 for _ in vector]
    return [float(value / norm) for value in vector]


class IndexStore:
    """Persist embeddings to disk and serve cosine similarity queries."""

    def __init__(self, dimension: int, *, index_name: str = "specs", settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._dimension = dimension
        self._index_name = index_name
        self._index_dir = Path(self._settings.RAG_INDEX_DIR)
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._index_dir / f"{self._index_name}.json"
        self._vectors: list[list[float]] = []
        self._normalized_vectors: list[list[float]] = []
        self._items: list[IndexItem] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    def build(self, vectors: Sequence[Sequence[float]], items: Sequence[IndexItem]) -> None:
        self._vectors = [list(map(float, vector)) for vector in vectors]
        self._items = [
            IndexItem(chunk_id=item.chunk_id, text=item.text, metadata=dict(item.metadata))
            for item in items
        ]
        if any(len(vector) != self._dimension for vector in self._vectors):
            raise ValueError("All vectors must match the configured dimension")
        self._normalized_vectors = [_normalize_vector(vector) for vector in self._vectors]
        self._persist()

    def _persist(self) -> None:
        payload = []
        for item, vector in zip(self._items, self._vectors):
            payload.append(
                {
                    "chunk_id": item.chunk_id,
                    "text": item.text,
                    "metadata": item.metadata,
                    "vector": vector,
                }
            )
        with self._index_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def load(self) -> None:
        if not self._index_path.exists():
            return
        with self._index_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._vectors = []
        self._items = []
        for entry in payload:
            vector = [float(value) for value in entry.get("vector", [])]
            if len(vector) != self._dimension:
                continue
            metadata = entry.get("metadata") or {}
            chunk_id = str(entry.get("chunk_id"))
            text = str(entry.get("text", ""))
            self._vectors.append(vector)
            self._items.append(IndexItem(chunk_id=chunk_id, text=text, metadata=dict(metadata)))
        self._normalized_vectors = [_normalize_vector(vector) for vector in self._vectors]

    def search(self, query_vector: Sequence[float], k: int) -> list[tuple[str, float, dict[str, object]]]:
        if not self._items:
            return []
        normalized_query = _normalize_vector(query_vector)
        scores: list[tuple[str, float, dict[str, object]]] = []
        for item, vector in zip(self._items, self._normalized_vectors):
            score = sum(a * b for a, b in zip(vector, normalized_query))
            scores.append((item.chunk_id, float(score), dict(item.metadata)))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:k]

    def clear(self) -> None:
        self._vectors = []
        self._normalized_vectors = []
        self._items = []
        if self._index_path.exists():
            self._index_path.unlink()

    def items(self) -> list[IndexItem]:
        return list(self._items)
