from __future__ import annotations

import numpy as np

from backend.config import Settings
from backend.services.header_locate_vector import locate_headers_with_vectors


class StubEmbeddings:
    def __init__(self, vectors: dict[str, np.ndarray], settings: Settings) -> None:
        self._vectors = vectors
        self.settings = settings

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.vstack(
            [self._vectors.get(text, np.zeros(2, dtype=np.float32)) for text in texts]
        ).astype(np.float32)


def test_vector_locator_enforces_monotonicity() -> None:
    settings = Settings()
    settings = settings.model_copy(
        update={
            "header_locate_fuse_weights": (0.9, 0.1, 0.0, 0.0),
            "header_locate_min_lexical": 0.0,
            "header_locate_min_cosine": 0.0,
            "header_locate_prefer_last_match": False,
        }
    )

    lines = [
        {"global_idx": 0, "page": 1, "line_idx": 0, "text": "Introduction", "top": 10.0},
        {"global_idx": 1, "page": 1, "line_idx": 1, "text": "Section B", "top": 20.0},
        {"global_idx": 2, "page": 2, "line_idx": 0, "text": "Introduction", "top": 15.0},
    ]

    headers = [
        {"text": "Section B", "level": 1},
        {"text": "Introduction", "level": 1},
    ]

    vectors = {
        "Section B": np.array([0.0, 1.0], dtype=np.float32),
        "Introduction": np.array([1.0, 0.0], dtype=np.float32),
    }

    embedder = StubEmbeddings(vectors, settings)

    located = locate_headers_with_vectors(
        session=None,
        document_id=1,
        simple_headers=headers,
        lines=lines,
        settings=settings,
        tracer=None,
        embeddings_client=embedder,
    )

    assert [entry["global_idx"] for entry in located] == [1, 2]
