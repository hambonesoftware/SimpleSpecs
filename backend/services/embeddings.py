"""Embeddings service with deterministic hashing fallback."""
from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence

from ..config import Settings, get_settings

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

__all__ = ["EmbeddingService"]


def _ensure_list(vector: Sequence[float] | Iterable[float]) -> list[float]:
    if isinstance(vector, list):
        return [float(item) for item in vector]
    if hasattr(vector, "tolist"):
        return [float(item) for item in vector.tolist()]
    return [float(item) for item in vector]


def _normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return [0.0 for _ in values]
    return [float(value / norm) for value in values]


class EmbeddingService:
    """Produce sentence embeddings with optional hashing stub."""

    def __init__(self, settings: Settings | None = None, dimension: int = 384) -> None:
        self._settings = settings or get_settings()
        self._dimension = dimension
        self._light_mode = bool(self._settings.RAG_LIGHT_MODE)
        self._model: SentenceTransformer | None = None
        if not self._light_mode and SentenceTransformer is not None:
            try:
                self._model = SentenceTransformer(self._settings.RAG_MODEL_PATH)
                if hasattr(self._model, "get_sentence_embedding_dimension"):
                    self._dimension = int(self._model.get_sentence_embedding_dimension())
            except Exception:  # pragma: no cover - fallback to stub mode
                self._model = None
                self._light_mode = True

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is not None:
            vectors = self._model.encode(
                list(texts),
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return [_normalize(_ensure_list(vector)) for vector in vectors]
        return [self._hash_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if self._model is not None:
            vector = self._model.encode(
                [text],
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return _normalize(_ensure_list(vector[0]))
        return self._hash_vector(text)

    def batch_encode(self, batched_texts: Iterable[Sequence[str]]) -> Iterable[list[list[float]]]:
        for texts in batched_texts:
            yield self.embed_documents(list(texts))

    def _hash_vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        if not digest:
            return [0.0] * self._dimension
        values = [digest[i % len(digest)] for i in range(self._dimension)]
        mean = sum(values) / len(values)
        centered = [value - mean for value in values]
        return _normalize(centered)
