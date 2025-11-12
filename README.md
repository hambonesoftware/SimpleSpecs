# SimpleSpecs

SimpleSpecs parses engineering specification PDFs and structures the extracted data for downstream workflow automation.

## Local development
1. Create and activate a virtual environment:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the environment template and adjust values as needed:
   ```bash
   cp .env.template .env
   ```
4. Launch the backend locally (hot reload enabled):
   ```bash
   ./start_local.sh
   ```
   On Windows PowerShell:
   ```powershell
   .\start_local.bat
   ```
   The helper scripts honour `HOST`, `PORT`, and `LOG_LEVEL` if they are set in your `.env` file.
5. Visit `http://localhost:8000/api/health` to verify the service responds with `{ "ok": true }`.
6. Open `http://localhost:8000/` in your browser to use the SimpleSpecs web app; the FastAPI server serves the static frontend from the same origin.

   If you need to host the static files separately (for example during local prototyping), add a `<meta name="api-base">` tag to `frontend/index.html` or assign `window.API_BASE` at runtime with the full API origin (e.g. `http://127.0.0.1:8000`). The frontend falls back to the same origin when no override is provided.

The server creates the `uploads/` and `exports/` directories on startup if they are missing. Adjust their locations via the `UPLOAD_DIR` and `EXPORT_DIR` environment variables.

### Per-Section Spec Extraction (Agents)

SimpleSpecs now persists every aligned header section and can fan out five discipline-specific agents to extract structured requirements. The workflow stores all artefacts in a dedicated SQLite database (default `SPECS_DB_URL=sqlite:////tmp/simplespecs.db`). Configure the models and retry window with the following environment variables:

```
SPECS_PRIMARY_MODEL=anthropic/claude-3.5-sonnet
SPECS_FALLBACK_MODEL=openai/gpt-4.1-mini
SPECS_TIMEOUT_S=120
SPECS_RETRY_MAX=1
SPECS_BACKOFF_S=1.5
```

**API endpoints**

- `POST /api/specs/dispatch { "documentId": "123" }` queues five jobs per aligned section.
- `GET  /api/specs?documentId=123` returns every section with per-agent results.
- `GET  /api/specs/{sectionId}` fetches a single section payload.
- `GET  /api/specs/status?documentId=123` reports aggregate completion counts.

Jobs run in-process using FastAPI background tasks. Results are stored in `spec_records` with one row per `(section, agent)` pair. For local experiments you can trigger the workflow from the CLI:

```bash
python scripts/specs_dispatch.py 123 --run
```

After running the header alignment flow (`POST /api/headers/{document_id}`) the frontend shows an **Analyze Specs** button beside the aligned sections. Clicking the button dispatches the jobs, polls the status endpoint, and renders the accordion view once all agents complete. Use the dropdown filters to focus on specific disciplines or requirement levels.

The specs database is initialised automatically on import; use `SPECS_DB_URL` to point to a persistent location in production.

### Header extraction configuration

SimpleSpecs sends the full document text to OpenRouter for a high-fidelity outline. Configure behaviour via the following environment variables (also available in `.env.template`):

- `HEADERS_MODE`: keep `llm_full` to enable the OpenRouter pipeline.
- `HEADERS_LLM_MODEL`: fully qualified OpenRouter model identifier (default `anthropic/claude-3.5-sonnet`).
- `HEADERS_LLM_MAX_INPUT_TOKENS`: approximate token budget per request chunk (default `120000`).
- `HEADERS_LLM_TIMEOUT_S`: request timeout in seconds (default `120`).
- `HEADERS_LLM_CACHE_DIR`: on-disk cache for previously processed documents.
- `HEADERS_CACHE_TO_DB`: set to `0` to disable persisting raw outlines to SQLite (disk caching remains active).

The pipeline requires `OPENROUTER_API_KEY`. Cached responses avoid repeated model invocations for unchanged documents.

#### Sequential alignment strategy

The default header locator uses a forward-only, parent-bounded sequential search that resists table-of-contents anchors and running headers. Tune behaviour via these environment variables:

```
HEADERS_ALIGN_STRATEGY=sequential  # use `legacy` to revert to the prior locator
HEADERS_SUPPRESS_TOC=1            # ignore pages that look like TOCs
HEADERS_SUPPRESS_RUNNING=1        # filter repeated running headers/footers
HEADERS_NORMALIZE_CONFUSABLES=1   # normalise numeric lookalikes (I/l → 1)
HEADERS_FUZZY_THRESHOLD=80        # token-set similarity for title matching
HEADERS_WINDOW_PAD_LINES=40       # expand parent search windows by ±N lines
HEADERS_BAND_LINES=5              # top/bottom lines per page considered a running band
HEADERS_L1_REQUIRE_NUMERIC=1      # insist on numeric prefixes for L1 anchors before fallback
HEADERS_L1_LOOKAHEAD_CHILD_HINT=30  # scan ahead for 1.1-style hints when ranking anchors
HEADERS_MONOTONIC_STRICT=1        # enforce forward-only anchoring with duplicate retries
HEADERS_REANCHOR_PASS=1           # repair parents that landed after their children
```

Recent hardening adds:

- Numeric-first anchoring for level-1 chapters with optional text fallback.
- A strict monotonic gate that re-tries later duplicates when a candidate appears too early.
- Page-band and running-header suppression so top/bottom banners never win.
- A coherence re-anchor sweep that repositions parents ahead of their children.

Enable tracing to inspect the sequential decisions end-to-end:

```
HEADERS_ALIGN_STRATEGY=sequential HEADERS_TRACE=1 \
curl -X POST "http://localhost:8000/api/headers/{document_id}?align=sequential&trace=1"
```

#### Bullet-proof sequential invariants

For the most robust experience enable the invariant sweep (defaults shown):

```
HEADERS_ALIGN_STRATEGY=sequential
HEADERS_STRICT_INVARIANTS=1
HEADERS_TITLE_ONLY_REANCHOR=1
HEADERS_BAND_LINES=5
HEADERS_RESCAN_PASSES=2
HEADERS_DEDUPE_POLICY=best
```

### DB-first header retrieval

Header discovery now hydrates the UI from the persisted SQLite cache before invoking the LLM:

1. `GET /api/documents/{document_id}/status` returns `{ parsed: bool, headers: bool }`. When `parsed` is `false`, the frontend calls `POST /api/parse/{document_id}` until the document is parsed.
2. If `headers` is `true`, `GET /api/headers/{document_id}` returns the stored outline, metadata, and aligned sections without touching the LLM.
3. `GET /api/headers/{document_id}/outline` exposes only the raw outline payload and metadata (useful for tooling).
4. `POST /api/headers/{document_id}` refreshes the outline on demand. The handler deduplicates runs by `document_id` + `prompt_hash` + `source_hash`, marks prior runs as `superseded`, writes the outline to both SQLite (`header_outline_cache`) and the on-disk cache (`HEADERS_LLM_CACHE_DIR`), persists aligned sections, and finally re-reads the payload from the database.

Sample response from `GET /api/headers/42`:

```json
{
  "documentId": 42,
  "runId": 7,
  "outline": { "headers": [{ "text": "Introduction", "number": "1" }] },
  "meta": {
    "model": "anthropic/claude-3.5-sonnet",
    "promptHash": "9b0d…",
    "sourceHash": "c2a1…",
    "tokens": { "prompt": null, "completion": null },
    "latencyMs": 1842,
    "createdAt": "2025-01-01T00:00:00+00:00"
  },
  "sections": [
    {
      "section_key": "intro",
      "title": "Introduction",
      "number": "1",
      "level": 1,
      "start_global_idx": 12,
      "end_global_idx": 48,
      "start_page": 2,
      "end_page": 3
    }
  ],
  "simpleheaders": [
    {
      "text": "Introduction",
      "number": "1",
      "level": 1,
      "page": 2,
      "global_idx": 12,
      "section_key": "intro"
    }
  ],
  "mode": "llm_full"
}
```

When `HEADERS_CACHE_TO_DB=0`, sections continue to persist in SQLite but the raw outline is only written to disk; the GET endpoints will respond with `404` until a new cached outline is created.

When tracing (`?trace=1`) the sequential tracer records the corrective steps taken during the invariant loop, including
`reanchor_parent`, `reanchor_parent_implied`, `child_relocate_to_window`, `dedupe_drop`, and per-pass `invariants_pass` summaries.

Clients can override the active strategy per request with `POST /api/headers/{document_id}?align=sequential` (or `align=legacy`). When tracing is enabled the sequential locator emits events such as `anchor_candidate_top`, `window_top`, and `anchor_resolved_child` to aid debugging.


#### Vector-enhanced locator (opt-in)

Set `HEADER_LOCATE_USE_EMBEDDINGS=1` to swap the sequential window search for a vector-guided locator. The LLM outline remains the source of truth—each header is matched against sliding line windows scored via lexical BM25/fuzzy matching, cosine similarity, font size, and page position. Candidates that resemble TOC entries (dot leaders, "contents", index terms) or running headers are discarded before selection.

Key tuning knobs:

```
HEADER_LOCATE_USE_EMBEDDINGS=1           # enable vector fusion
HEADER_LOCATE_FUSE_WEIGHTS=0.55,0.30,0.10,0.05  # lexical, cosine, font-rank, vertical bonuses
HEADER_LOCATE_MIN_LEXICAL=0.30           # minimum lexical score to keep a candidate
HEADER_LOCATE_MIN_COSINE=0.25            # minimum cosine similarity
HEADER_LOCATE_PREFER_LAST_MATCH=1        # favour later matches when scores tie (avoids TOC hits)
```

Embeddings default to the local `sentence-transformers/all-MiniLM-L6-v2` model. Override the provider or remote model via:

```
EMBEDDINGS_PROVIDER=local                # or 'openrouter'
EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDINGS_CACHE_DIR=.cache/emb          # per-text + per-document vector cache
EMBEDDINGS_OPENROUTER_MODEL=openai/text-embedding-3-small
EMBEDDINGS_OPENROUTER_TIMEOUT_S=60
```

When `HEADERS_TRACE=1` (or `?trace=1`), the vector locator logs ranked candidates per header and writes `exports/{doc_id}/header_locations.json` with the top three matches and their component scores for offline analysis.


#### Strict Lockdown mode

The strict LLM-backed locator hardens matching for tricky numbering and appendix layouts:

- Normalises `I`/`l` → `1`, collapses spaced dot separators, and replaces NBSP variants prior to scoring.
- Detects and suppresses TOC/summary pages by counting dotted leaders and dense section-like tokens.
- Prefers the first candidate after the previous anchor, with a last-occurrence fallback when the document repeats numbers.
- Fuses two-line `APPENDIX A` headings for scoring while keeping the anchor on the first line.
- Runs a final monotonic guard that re-resolves children that slipped ahead of their parents.

Environment toggles (defaults shown):

```
HEADERS_STRICT_FUZZY_THRESH=75
HEADERS_STRICT_TITLE_ONLY_THRESH=72
HEADERS_STRICT_BAND_LINES=3
HEADERS_STRICT_TOC_MIN_SECTION_TOKENS=6
HEADERS_STRICT_TOC_MIN_DOT_LEADERS=4
HEADERS_STRICT_AFTER_ANCHOR_ONLY=1
HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK=1
HEADERS_FINAL_MONOTONIC_GUARD=1
```

### Hybrid extractor

SimpleSpecs now extracts body lines via a hybrid engine that keeps the strict matcher unchanged while improving noisy PDFs:

- Primary: **PyMuPDF** word-to-line grouping sorted by `(y, x)` reading order.
- Fallback: **pypdfium2** whenever the document exhibits spaced-dot numbering or `1`/`I` confusables.
- Output shape: each line is a dict `{ text, page, global_idx, bbox }` with stable ordering across the document.

Control behaviour with environment variables (defaults shown):

```
PARSER_ENGINE=auto                  # choose `fitz`, `pdfium`, or `auto`
PARSER_LINE_Y_TOLERANCE=2.0         # PyMuPDF word grouping tolerance in px
PARSER_NOISE_SPACED_DOT_THRESH=0.18 # spaced-dot ratio to trigger pdfium fallback
PARSER_NOISE_CONFUSABLE_1_THRESH=0.12  # confusable "I"→"1" ratio threshold
PARSER_KEEP_BBOX=1                  # keep bounding boxes when available
```

Why it helps:

- Normalises NBSPs, soft hyphens, and dotted numbering artefacts before matching.
- Keeps strict TOC gating, after-anchor vs. last-occurrence rules, and the final monotonic guard intact.
- Provides consistent bounding boxes so running-header suppression and downstream tools keep functioning.

### Header trace debugging

Set the following flags to capture a detailed, end-to-end trace of header discovery:

```
HEADERS_TRACE=1
HEADERS_TRACE_DIR=backend/logs/headers
HEADERS_TRACE_EMBED_RESPONSE=1  # optional: echo events in API responses
HEADERS_LOG_LEVEL=DEBUG
```

With tracing enabled, each call to `POST /api/headers/{document_id}?trace=1` writes a JSONL file under `HEADERS_TRACE_DIR` and, when `trace=1` (or `HEADERS_TRACE_EMBED_RESPONSE=1`), returns the events inline:

```bash
curl -X POST "http://localhost:8000/api/headers/42?trace=1" \
  -H "accept: application/json"
```

Each trace entry captures the reasoning behind the locator, including:

- `start_run`, `doc_stats`, and `end_run` – run metadata, document shape, timings, and unresolved headers.
- `pre_normalize_sample` / `normalized_line` – representative text before and after cleanup.
- `toc_detected` / `running_header_filtered` – TOC and running-header suppression decisions.
- `llm_outline_received` – outline size sampled from the LLM.
- `candidate_found`, `candidate_scored`, `anchor_resolved`, `monotonic_violation`, `fallback_triggered` – per-header search and alignment decisions, including gap fills.

Trace files are newline-delimited JSON and can be streamed into tooling such as `jq` for analysis.


## Windows single-file bundle (optional)
A PyInstaller spec is provided for packaging the backend as a single executable on Windows.

1. Install build prerequisites in a clean virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt pyinstaller
   ```
2. Generate the bundle:
   ```powershell
   pyinstaller simplespecs.spec
   ```
3. The packaged binary and supporting files are produced in the `dist/SimpleSpecs` directory. Launch `SimpleSpecs.exe` to start the API server (respects the same `.env` settings as the scripts).

## Testing
Run the automated test suite with:
```bash
pytest
```

## Project structure
```
backend/      # FastAPI application
frontend/     # Static HTML/CSS/JS assets
plan/         # Phase plans and reference documents
agents/       # Codex-style execution prompts per phase
```
