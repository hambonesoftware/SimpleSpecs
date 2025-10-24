# Phase 03 — Header & Subheader Extraction (LLM + Rules)

## Objectives
- Build hierarchical outline using regex/heuristics + LLM confirmation.

## Scope
- New `/api/headers` that consumes parse artifacts and returns fenced outline.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 02 parse artifacts available.

## Tasks
- `_headers_common.py`: patterns for numeric/alpha/roman; indentation; font-size boosts.
- TOC exclusion: reject lines appearing within detected TOC windows.
- Build candidate header list; score; produce preliminary outline.
- Call OpenRouter with Header Tree prompt (see Prompts-Library) to refine/normalize.
- Validate returned `#headers#` fence; re-try with stricter instructions if invalid.
- Persist outline snapshot as golden under tests when approved.

## API Endpoints (new/changed)
- `POST /api/headers/{doc_id}` → `#headers#` fenced text + JSON outline.

## Config & Flags
- `LLM_PROVIDER`, `OPENROUTER_API_KEY`.
- Model params hardened with `max_tokens` up-bump.

## Prompts (if applicable)
- Header Tree Extraction (from Prompts-Library.md).

## Artifacts & Deliverables
- Outline JSON + fenced text; diff viewer on frontend.

## Acceptance Criteria / Exit Gates
- ≥ 99% header recall on samples; manual spot-checks pass.

## Risks & Mitigations
- Over-inclusion of bold body lines; mitigated by font-size/weight thresholds + regex validation.

## Rollback
- Return to regex-only outline; disable LLM refinement flag.
