# Phase 09 — Testing, Validation, and Hardening

## Objectives
- Achieve coverage targets; harden endpoints; finalize goldens.

## Scope
- Unit + integration + e2e; fuzz body text; negative tests.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- All prior phases feature-complete.

## Tasks
- Unit tests for each service and router.
- Integration tests with mocked LLM provider and sample PDFs.
- Golden snapshot refresh with sign-off.
- Security review: input size caps, MIME checks, path traversal prevention.
- Performance tuning: concurrency settings, streaming, caching.

## API Endpoints (new/changed)
_No new APIs._

## Config & Flags
- `MAX_UPLOAD_MB`, `REQUEST_TIMEOUTS`, `WORKERS`.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Coverage report; test badges; performance notes.

## Acceptance Criteria / Exit Gates
- CI green; coverage ≥ target; soak tests stable.

## Risks & Mitigations
- Flaky tests; stabilize with fixtures and deterministic seeds.

## Rollback
- Revert high-risk optimizations; keep stable baseline.
