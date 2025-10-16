# SimpleSpecs — Phase P0

Phase P0 delivers the core FastAPI skeleton, configuration contracts, and mock endpoints for the UNO-less parsing stack with an optional MinerU toggle.

## Prerequisites
- Python 3.12+

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Running the API
```bash
uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) to view the scaffolded UI and [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for API documentation.

## Configuration
Settings are loaded from environment variables (prefixed with `SIMPLS_` when desired). Key options include:

- `PDF_ENGINE` — `native`, `mineru`, or `auto` (default `native`)
- `MINERU_ENABLED` — enables MinerU integrations when true (default `false`)
- `MINERU_MODEL_OPTS` — JSON/dict style mapping for MinerU models
- `ALLOW_ORIGINS` — comma-separated origins for CORS (default `*`)
- `MAX_FILE_MB` — maximum upload size (default `50`)
- `PARSER_MULTI_COLUMN` — enable column clustering for reading order reconstruction (default `true`)
- `HEADERS_SUPPRESS_TOC` — drop table-of-contents pages when evaluating headers (default `true`)
- `HEADERS_SUPPRESS_RUNNING` — filter recurring running headers/footers (default `true`)
- `PARSER_ENABLE_OCR` — invoke Tesseract OCR on text-light pages when available (default `false`)
- `PARSER_DEBUG` — emit structured JSON debug logs during native parsing (default `false`)
- `RAG_ENABLE` — toggles the retrieval-augmented spec workflows (default `true`)
- `RAG_CHUNK_MODE` — hard-enforced to `section`; overrides any token length or overlap settings
- `RAG_MODEL_PATH` — local embeddings model path (default `./models/all-MiniLM-L6-v2`)
- `RAG_INDEX_DIR` — directory used for persisted RAG indices (default `./.rag_index`)
- `RAG_LIGHT_MODE` — set to `1` for offline hashing stubs during CI/local smoke tests (default `1`)
- `RAG_HYBRID_ALPHA` — blend weight between sparse and dense scores during hybrid search (default `0.5`)
- `RAG_DEBUG` — when truthy, persist section/spec JSONL traces to `./debug` and emit fusion score logs

> **Note**
> When `RAG_CHUNK_MODE` is present it is locked to `section`, ensuring exactly one
> chunk per document section regardless of legacy token-size or overlap
> configuration.

### Native header parsing CLI

The layout-aware parser can be exercised locally without the API server:

```bash
python -m backend.cli.parse_headers path/to/document.pdf --json headers.json --debug
```

The optional `--debug` flag toggles `PARSER_DEBUG` logging and echoes the active
feature flags for quick verification.

## Specification RAG workflow

The section-based chunker, rule-driven atomizer, and hybrid search endpoints
run fully offline when `SIMPLS_RAG_LIGHT_MODE=1` (the default). To extract and
index specifications for a processed upload, run:

```bash
python -m backend.cli.specs_index <file_id_or_source_path> --rebuild
```

Passing a PDF path with `--rebuild` stages the document under `ARTIFACTS_DIR`, reruns
parsing, chunking, and atomization, and refreshes the hybrid index in one step.

Query the indexed specifications locally without the API server:

```bash
python -m backend.cli.specs_query --file-id <file_id> --q "24 VDC safety relay" --k 5
```

If no index exists yet the query helper instructs you to rebuild first, rather than
terminating with a traceback.

The FastAPI layer also exposes additive endpoints:

- `POST /api/specs/extract` — run atomization over chunked sections.
- `POST /api/specs/index` — persist hybrid embeddings/BM25 index data.
- `POST /api/specs/search` — return weighted hybrid hits.
- `POST /api/specs/export` — retrieve the stored specification payload.

## Tests
```bash
pytest -q
```

## Baseline Replay

The phase P0 baseline fixtures in `tests/golden/before/` can be regenerated or
verified with the replay script:

```bash
python scripts/run_headers.py record MFC-5M_R2001_E1985.pdf
python scripts/run_headers.py record "Epf, Co.pdf"

# Validate both fixtures match the committed golden files
python scripts/run_headers.py check

# Replay a stored upload without re-specifying the PDF path
python scripts/run_headers.py record --upload-id <upload_id>
python scripts/run_headers.py check --upload-id <upload_id>
```

The `Golden Header Replay` GitHub Actions workflow runs the same `check`
command for every pull request and uploads debug artifacts if a mismatch is
detected.
