# Phase 07 — Frontend Modernization (ESM‑JS UI)

## Objectives
- Deliver a lightweight, responsive UI with upload, outlines, spec buckets, and risk.

## Scope
- Pure HTML/CSS + ESM-JS modules; no framework build step.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phases 01–06 APIs available.

## Tasks
- `index.html` layout: left nav (files), main panels (Parse, Headers, Specs, Risk).
- `js/api.js`: wrapper for fetch calls with JSON/error handling.
- `js/ui.js`: render tables, collapsible trees, toasts, spinners.
- CSV/JSON export buttons; 'Approve' action for spec records.
- Accessibility pass (keyboard nav) and responsive CSS.

## API Endpoints (new/changed)
- Consumes all REST APIs defined earlier.

## Config & Flags
- Base API URL from `<meta>` or data-attr.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Usable UI across desktop/tablet; dark-mode friendly.

## Acceptance Criteria / Exit Gates
- All flows usable without refresh; errors surfaced gracefully.

## Risks & Mitigations
- Large result rendering; virtualize long lists if needed.

## Rollback
- Minimal UI (plain tables) with same endpoints.
