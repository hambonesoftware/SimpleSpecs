# Phase 10 — Deployment & Packaging

## Objectives
- Provide on‑prem and local packaging; document ops procedures.

## Scope
- Dockerfile, compose, secrets handling; optional PyInstaller bundle (Windows).

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 09 complete.

## Tasks
- Multi-stage Dockerfile; copy `frontend/` as static via FastAPI mount.
- Health/readiness endpoints; compose with volume mounts for uploads/exports.
- Secrets: mount `OPENROUTER_API_KEY`; prod `.env` example.
- Windows single-file build via PyInstaller (optional).
- Final README with run, backup, and upgrade steps.

## API Endpoints (new/changed)
- `GET /api/health` for readiness/liveness.

## Config & Flags
- `PORT`, `HOST`, `LOG_LEVEL`, `DB_URL` overrides.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- `docker run` and `docker compose up` both functional; Windows EXE (optional).

## Acceptance Criteria / Exit Gates
- Cold start < 3s on dev box; docs clear; smoke test passes.

## Risks & Mitigations
- Large images; use slim base and multi-stage to minimize size.

## Rollback
- Provide non-Docker local run scripts as fallback.
