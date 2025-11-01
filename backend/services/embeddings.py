"""Embedding utilities for the vector-based header locator."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import requests

from backend.config import EMBEDDINGS_CACHE_DIR, EMBEDDINGS_PROVIDER
from backend.config import EMBEDDINGS_MODEL as DEFAULT_EMBEDDINGS_MODEL
from backend.config import EMBEDDINGS_OPENROUTER_MODEL
from backend.config import EMBEDDINGS_OPENROUTER_TIMEOUT_S
from backend.config import Settings


def _normalise_query(text: str) -> str:
    """Return the text prepared for embedding requests."""

    text = (text or "").strip()
    if not text:
        return "heading: (empty)"
    if len(text.split()) < 4:
        return f"heading: {text}"
    return text


class EmbeddingsClient:
    """Lightweight embeddings helper with local and OpenRouter providers."""

    _model_lock = threading.Lock()
    _local_model = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = (settings.embeddings_provider or EMBEDDINGS_PROVIDER).strip().lower()
        self.model_name = settings.embeddings_model or DEFAULT_EMBEDDINGS_MODEL
        self.remote_model = (
            settings.embeddings_openrouter_model or EMBEDDINGS_OPENROUTER_MODEL
        )
        self.remote_timeout = (
            settings.embeddings_openrouter_timeout_s or EMBEDDINGS_OPENROUTER_TIMEOUT_S
        )
        cache_dir = settings.embeddings_cache_dir or Path(EMBEDDINGS_CACHE_DIR)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def embed(self, text: str) -> np.ndarray:
        """Return the embedding for ``text``."""

        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return embeddings for ``texts`` with caching."""

        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        prepared = [_normalise_query(text) for text in texts]
        cached: list[np.ndarray | None] = [None] * len(prepared)
        pending: list[str] = []
        pending_indices: list[int] = []

        for index, text in enumerate(prepared):
            cache_path = self._cache_path(text)
            if cache_path.exists():
                try:
                    cached[index] = np.load(cache_path)
                    continue
                except Exception:
                    cache_path.unlink(missing_ok=True)
            pending.append(text)
            pending_indices.append(index)

        if pending:
            fresh = self._embed_uncached(pending)
            if fresh.shape[0] != len(pending_indices):
                raise RuntimeError("Embedding provider returned unexpected vector count")
            for offset, index in enumerate(pending_indices):
                cached[index] = fresh[offset]
                self._store_cache(prepared[index], fresh[offset])

        stacked = [vector for vector in cached if vector is not None]
        if len(stacked) != len(prepared):
            raise RuntimeError("Failed to resolve all embeddings from cache/provider")

        return np.vstack(stacked).astype(np.float32, copy=False)

    # Internal helpers -------------------------------------------------

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.npy"

    def _store_cache(self, text: str, vector: np.ndarray) -> None:
        cache_path = self._cache_path(text)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache_path, vector.astype(np.float32, copy=False))

    def _embed_uncached(self, texts: Sequence[str]) -> np.ndarray:
        if self.provider == "openrouter":
            return self._embed_via_openrouter(texts)
        return self._embed_via_local(texts)

    def _embed_via_local(self, texts: Sequence[str]) -> np.ndarray:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "sentence-transformers is required for local embeddings"
            ) from exc

        with self._model_lock:
            if self._local_model is None:
                self._local_model = SentenceTransformer(self.model_name)
        vectors = self._local_model.encode(  # type: ignore[operator]
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def _embed_via_openrouter(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        api_key = (self.settings.openrouter_api_key or "").strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for remote embeddings")

        url = "https://openrouter.ai/api/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
            headers["Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_title:
            headers["X-Title"] = self.settings.openrouter_title

        payload = {
            "model": self.remote_model,
            "input": list(texts),
        }

        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=self.remote_timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter embeddings request failed ({response.status_code})"
            )

        data = response.json()
        vectors: list[list[float]] = []
        for item in data.get("data", []):
            vector = item.get("embedding")
            if isinstance(vector, Iterable):
                vectors.append(list(vector))

        if len(vectors) != len(texts):
            raise RuntimeError("OpenRouter embeddings response mismatch")

        arr = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


__all__ = ["EmbeddingsClient"]

