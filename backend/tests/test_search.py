from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.services.embeddings import EmbeddingService
from backend.services.index_store import IndexStore
from backend.services.search import ChunkRecord, HybridSearch


def test_hybrid_search_ranks_relevant_chunks(tmp_path) -> None:
    settings = Settings(RAG_INDEX_DIR=str(tmp_path / "index"), RAG_LIGHT_MODE=1)
    embedding = EmbeddingService(settings)
    index_store = IndexStore(embedding.dimension, index_name="unit", settings=settings)
    searcher = HybridSearch(embedding_service=embedding, index_store=index_store, settings=settings)

    records = [
        ChunkRecord(
            chunk_id="chunk-1",
            text="The safety relay shall operate on a 24 VDC supply with redundant contacts.",
            metadata={"header_path": "Document / Safety"},
        ),
        ChunkRecord(
            chunk_id="chunk-2",
            text="Maintain 5 mm clearance around the enclosure for cooling airflow.",
            metadata={"header_path": "Document / Mechanical"},
        ),
        ChunkRecord(
            chunk_id="chunk-3",
            text="Provide software update checklist and operator documentation.",
            metadata={"header_path": "Document / Software"},
        ),
    ]

    searcher.index(records)
    assert len(searcher.records()) == 3

    results = searcher.search("24 VDC safety relay", k=2)
    assert results
    assert results[0]["chunk_id"] == "chunk-1"
    assert results[0]["metadata"]["header_path"] == "Document / Safety"
    assert results[0]["bm25"] > 0

    software_results = searcher.search("software checklist", k=2)
    assert software_results[0]["chunk_id"] == "chunk-3"

    reloaded = IndexStore(embedding.dimension, index_name="unit", settings=settings)
    reloaded.load()
    vector_hits = reloaded.search(embedding.embed_query("24 VDC safety relay"), k=3)
    assert any(hit[0] == "chunk-1" for hit in vector_hits)
