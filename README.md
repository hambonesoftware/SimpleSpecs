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

### Header extraction configuration

SimpleSpecs sends the full document text to OpenRouter for a high-fidelity outline. Configure behaviour via the following environment variables (also available in `.env.template`):

- `HEADERS_MODE`: keep `llm_full` to enable the OpenRouter pipeline.
- `HEADERS_LLM_MODEL`: fully qualified OpenRouter model identifier (default `anthropic/claude-3.5-sonnet`).
- `HEADERS_LLM_MAX_INPUT_TOKENS`: approximate token budget per request chunk (default `120000`).
- `HEADERS_LLM_TIMEOUT_S`: request timeout in seconds (default `120`).
- `HEADERS_LLM_CACHE_DIR`: on-disk cache for previously processed documents.

The pipeline requires `OPENROUTER_API_KEY`. Cached responses avoid repeated model invocations for unchanged documents.

#### Best-practice alignment strategy (`align=best`)

The production-grade "best" strategy is now the default. It layers multiple signals to reliably anchor LLM-provided outlines:

- Normalises numbering and OCR artefacts (e.g. `1 .I` → `1.1`) before scoring.
- Suppresses TOC/running headers by detecting dotted leaders and repeated band lines.
- Factors in typography (larger fonts, bold weight) when ranking candidates.
- Anchors sequentially, with a last-occurrence fallback that still respects TOC bans.
- Constrains children to hierarchical windows derived from their parents.
- Applies a final monotonic guard so parents always precede descendants.
- Emits rich trace events such as `candidate_found`, `anchor_resolved_best`, and `final_monotonic_pass_best` when tracing.

Toggle via `HEADERS_ALIGN_STRATEGY=best` or per-request with `?align=best`. Combine with `HEADERS_TRACE=1` to inspect the new trace events.

#### Sequential alignment strategy (legacy)

The legacy forward-only sequential locator remains available for comparison and regression checks. Tune behaviour via these environment variables:

```
HEADERS_ALIGN_STRATEGY=sequential  # use `legacy` to revert to the prior locator
HEADERS_SUPPRESS_TOC=1            # ignore pages that look like TOCs
HEADERS_SUPPRESS_RUNNING=1        # filter repeated running headers/footers
HEADERS_NORMALIZE_CONFUSABLES=1   # normalise numeric lookalikes (I/l → 1)
HEADERS_FUZZY_THRESHOLD=80        # token-set similarity for title matching
HEADERS_WINDOW_PAD_LINES=40       # expand parent search windows by ±N lines
HEADERS_BAND_LINES=3              # top/bottom lines per page considered a running band
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

When tracing (`?trace=1`) the sequential tracer records the corrective steps taken during the invariant loop, including
`reanchor_parent`, `reanchor_parent_implied`, `child_relocate_to_window`, `dedupe_drop`, and per-pass `invariants_pass` summaries.

Clients can override the active strategy per request with `POST /api/headers/{document_id}?align=sequential` (or `align=legacy`). When tracing is enabled the sequential locator emits events such as `anchor_candidate_top`, `window_top`, and `anchor_resolved_child` to aid debugging.


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


## Strict Guardrails & Trace

- **Preconditions**
  - Abort with HTTP 422 `no_lines` when extraction returns zero lines. Controlled via `HEADERS_STRICT_ABORT_ON_NO_LINES`.
  - Size guard logs `outline_skipped: size_guard` when estimated tokens exceed `HEADERS_MAX_DOC_TOKENS`.
- **LLM outline**
  - Emits `outline_call_start` / `outline_call_end` events describing provider, model, bytes, and status.
  - `_parse_outline_strict` records `outline_parse_ok` or `outline_parse_failed` (`empty_raw`, `non_list_json`, `json_items_missing_fields`, `no_json_no_bullets`, …).
  - Empty outline parses raise HTTP 422 `empty_outline` (configurable with `HEADERS_STRICT_FAIL_ON_EMPTY_OUTLINE`).
- **Trace events**
  - `doc_stats`, `outline_skipped`, `abort_no_lines`, `abort_empty_outline`, `strict_align_done`, `end_run`, and more.
  - When `?trace=1` (or `HEADERS_TRACE_EMBED_RESPONSE=1`), responses include inline trace data and the persisted trace file path.


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
