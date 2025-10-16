"""Hybrid sparse/dense search utilities."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

from ..config import Settings, get_settings
from .embeddings import EmbeddingService
from .index_store import IndexItem, IndexStore

__all__ = ["ChunkRecord", "BM25Corpus", "HybridSearch"]

_TOKEN_RE = re.compile(r"[\w%°\.]+", re.UNICODE)


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    text: str
    metadata: dict[str, object]


class BM25Corpus:
    """Simplified BM25 scorer."""

    def __init__(self, documents: Sequence[ChunkRecord]) -> None:
        self._documents = list(documents)
        self._doc_lengths: list[int] = []
        self._avg_len = 0.0
        self._idf: dict[str, float] = {}
        self._doc_term_freqs: list[dict[str, int]] = []
        self._build()

    def _build(self) -> None:
        doc_freqs: dict[str, int] = {}
        for record in self._documents:
            tokens = self._tokenize(record.text)
            term_counts: dict[str, int] = {}
            for token in tokens:
                term_counts[token] = term_counts.get(token, 0) + 1
            self._doc_term_freqs.append(term_counts)
            self._doc_lengths.append(len(tokens))
            for token in term_counts:
                doc_freqs[token] = doc_freqs.get(token, 0) + 1
        if self._doc_lengths:
            self._avg_len = sum(self._doc_lengths) / len(self._doc_lengths)
        total_docs = len(self._documents)
        self._idf = {
            token: math.log(1 + (total_docs - freq + 0.5) / (freq + 0.5))
            for token, freq in doc_freqs.items()
        }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower() for token in _TOKEN_RE.findall(text)]

    def score(self, query: str, *, k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
        tokens = self._tokenize(query)
        scores: dict[str, float] = {}
        for doc_index, term_counts in enumerate(self._doc_term_freqs):
            score = 0.0
            doc_len = self._doc_lengths[doc_index] or 1
            for token in tokens:
                freq = term_counts.get(token)
                if not freq:
                    continue
                idf = self._idf.get(token, 0.0)
                denom = freq + k1 * (1 - b + b * doc_len / (self._avg_len or 1.0))
                score += idf * (freq * (k1 + 1)) / denom
            if score > 0.0:
                scores[self._documents[doc_index].chunk_id] = score
        return scores


class HybridSearch:
    """Hybrid search using dense vectors and BM25 fusion."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        index_store: IndexStore | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedding = embedding_service or EmbeddingService(self._settings)
        self._index = index_store or IndexStore(self._embedding.dimension, settings=self._settings)
        self._alpha = float(self._settings.RAG_HYBRID_ALPHA)
        self._records: list[ChunkRecord] = []
        self._bm25: BM25Corpus | None = None
        self._record_map: dict[str, ChunkRecord] = {}

    def index(self, records: Sequence[ChunkRecord]) -> None:
        self._records = list(records)
        self._record_map = {record.chunk_id: record for record in self._records}
        self._bm25 = BM25Corpus(self._records)
        embeddings = self._embedding.embed_documents([record.text for record in self._records])
        items = [
            IndexItem(chunk_id=record.chunk_id, text=record.text, metadata=record.metadata)
            for record in self._records
        ]
        self._index.build(embeddings, items)

    def search(self, query: str, k: int = 5) -> list[dict[str, object]]:
        if not self._records:
            return []
        bm25_scores = self._bm25.score(query) if self._bm25 else {}
        dense_vector = self._embedding.embed_query(query)
        dense_results = self._index.search(dense_vector, max(k, 10))
        dense_scores = {chunk_id: score for chunk_id, score, _ in dense_results}
        candidate_ids = set(bm25_scores) | set(dense_scores)
        results: list[tuple[str, float, float, float]] = []
        for chunk_id in candidate_ids:
            bm25 = bm25_scores.get(chunk_id, 0.0)
            dense = dense_scores.get(chunk_id, 0.0)
            score = self._alpha * dense + (1.0 - self._alpha) * bm25
            results.append((chunk_id, score, bm25, dense))
        results.sort(key=lambda item: item[1], reverse=True)
        limited = results[:k]
        response: list[dict[str, object]] = []
        for chunk_id, score, bm25, dense in limited:
            record = self._record_map.get(chunk_id)
            if not record:
                continue
            response.append(
                {
                    "chunk_id": chunk_id,
                    "score": score,
                    "bm25": bm25,
                    "vector": dense,
                    "text": record.text,
                    "metadata": record.metadata,
                }
            )
        return response

    def records(self) -> list[ChunkRecord]:
        return list(self._records)
