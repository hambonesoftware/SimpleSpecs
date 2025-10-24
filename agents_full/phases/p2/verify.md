# VERIFY — P2: Section Chunking + Spec Atomization + RAG

Checklist (PASS/FAIL with evidence)
- Section-chunking enforced (1:1 header_path ↔ chunk), token/overlap ignored
- Atomizer: classification + unit normalization
- Embeddings/index/search work with RAG_LIGHT_MODE=1 (deterministic)
- `/api/specs/*` routes present; prior APIs intact
- CLI runs; tests & goldens pass; docs updated; CI green

Run
```
# Ensure fixtures exist for tests
mkdir -p backend/tests/resources
cp "Epf, Co.pdf" backend/tests/resources/sample1.pdf
cp MFC-5M_R2001_E1985.pdf backend/tests/resources/sample2.pdf

export RAG_ENABLE=true RAG_CHUNK_MODE=section RAG_LIGHT_MODE=1        RAG_MODEL_PATH=./models/all-MiniLM-L6-v2 RAG_INDEX_DIR=./.rag_index        PARSER_MULTI_COLUMN=true HEADERS_SUPPRESS_TOC=true HEADERS_SUPPRESS_RUNNING=true
pre-commit run --all-files
pytest -q --maxfail=1 --disable-warnings backend/tests/test_chunker.py backend/tests/test_atomizer.py backend/tests/test_search.py backend/tests/test_specs_routes.py

# CLI smoke
python -m backend.cli.specs_index backend/tests/resources/sample1.pdf --rebuild
python -m backend.cli.specs_query --q "24 VDC safety relay" --k 10
```
Use `_common/verify_report_template.md` for the report structure.
