# EXECUTE — P2: Section Chunking + Spec Atomization + RAG (One-Chunk-Per-Section)

Branch: p2-specs-rag
Override: `RAG_CHUNK_MODE=section` → exactly one chunk per section. Ignore token/overlap configs.

Repo Fixtures
```bash
mkdir -p backend/tests/resources
cp "Epf, Co.pdf" backend/tests/resources/sample1.pdf
cp MFC-5M_R2001_E1985.pdf backend/tests/resources/sample2.pdf
```

Deliverables
1) Section Chunker — `backend/services/chunker.py`
   - 1 chunk per `header_path`; exclude TOC/running headers; ignore token limits
2) Spec Atomizer — `backend/services/spec_atomizer.py` + `SpecItem` (additive to models)
3) Embeddings/Index/Search — `embeddings.py`, `index_store.py`, `search.py`
   - Deterministic stub when `RAG_LIGHT_MODE=1`; hybrid BM25+vector with fusion
4) APIs (additive) — `backend/app/routers/specs.py`
   - `/api/specs/extract`, `/api/specs/index`, `/api/specs/search`, `/api/specs/export`
5) CLI — `backend/cli/specs_index.py`, `backend/cli/specs_query.py`
6) Tests & Goldens — `test_chunker.py`, `test_atomizer.py`, `test_search.py`, `test_specs_routes.py`, golden specs
7) Docs — update `README` & `docs/DEV_SETUP.md` (section-chunking override; stub/full modes)

Acceptance
- 1:1 section ↔ chunk; specs extracted & normalized; hybrid search returns relevant results offline
- Docs updated; tests & CI green; **no breaking changes** to prior phases
