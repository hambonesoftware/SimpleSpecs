# Phase 08 — Persistence, Reports, and Export

## Objectives
- Store and export reviewed specs with audit trail (ISO 9001 friendly).

## Scope
- SpecRecord model, approve/freeze flow, and DOCX/CSV exports.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phases 04/07.

## Tasks
- `models/spec_record.py`: id, doc_id, state, reviewer, timestamps, payload.
- `POST /api/specs/{doc_id}/approve` → transitions to 'approved' with hash.
- Exports: CSV for each department; DOCX via python-docx with header hierarchy.
- Audit log (who/when/what changed).

## API Endpoints (new/changed)
- `GET /api/specs/{doc_id}`
- `POST /api/specs/{doc_id}/approve`
- `GET /api/specs/{doc_id}/export?fmt=csv|docx`

## Config & Flags
- `EXPORT_DIR`, retention days.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Export artifacts written and downloadable from UI.

## Acceptance Criteria / Exit Gates
- Hash-stable exports; audit entries recorded.

## Risks & Mitigations
- Sensitive data leakage in exports; add PII scrub if needed.

## Rollback
- Disable exports; keep JSON-only download.
