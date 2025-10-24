# Phase 00 — Foundations & Environment

## Objectives
- Establish repo structure, environment, and CI/test harness.
- Provide `.env.template` and local run scripts.

## Scope
- No business logic; only scaffolding, install, CI, and smoke run.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- None.

## Tasks
- Initialize repo structure and Python 3.12 venv.
- Add `requirements.txt` and lockfile.
- Create `backend/main.py` with health endpoint.
- Add `.env.template` with toggles (see Config-Toggles.md).
- Add `start_local.sh/.bat` and `README` quickstart.
- Set up pytest and a minimal unit test for health route.

## API Endpoints (new/changed)
- `GET /api/health` → `{ "ok": true }`

## Config & Flags
- All toggles present but defaulted safe (OpenRouter off unless key provided).

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Running FastAPI app (`uvicorn backend.main:app`).
- CI that runs `pytest` and lint.

## Acceptance Criteria / Exit Gates
- `GET /api/health` returns 200.
- CI green.

## Risks & Mitigations
- Environment drift → lock versions; document Windows/macOS steps.

## Rollback
- Revert to initial commit; venv rebuild.
