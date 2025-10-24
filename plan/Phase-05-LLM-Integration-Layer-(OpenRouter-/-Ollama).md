# Phase 05 — LLM Integration Layer (OpenRouter / Ollama)

## Objectives
- Provide robust provider abstraction with retries, timeouts, and param hardening.

## Scope
- `services/llm.py` shared by headers/spec extraction and compliance checks.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 00/01; consumed by Phases 03/04/06.

## Tasks
- Implement `get_provider()`, `call_openrouter()`, `call_ollama()`.
- Add `max_tokens` bump logic and header passthrough (`HTTP-Referer`, `X-Title`).
- Strict fence validator; automatic retry with 'ONLY FENCED OUTPUT' preamble on failure.
- Token/cost logging; optional on-disk cache keyed by prompt+hash.
- Backoff strategy for rate limits; circuit breaker after N failures.

## API Endpoints (new/changed)
_Shared service; no public endpoint._

## Config & Flags
- `OPENROUTER_API_KEY`, `LLM_PROVIDER`, request timeouts, retry counts.

## Prompts (if applicable)
- All from Prompts-Library.md are routed through this layer.

## Artifacts & Deliverables
- Deterministic tests with mocked responses.

## Acceptance Criteria / Exit Gates
- 100% pass on provider unit tests; fences always validated or retried.

## Risks & Mitigations
- Provider outage; mitigated by Ollama fallback and cache.

## Rollback
- Fallback to rules-only mode in dependent phases.
