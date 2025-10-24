# Phase 01 — Backend Core & Document I/O

## Objectives
- Implement upload/list for PDFs; persist metadata; safe file handling.

## Scope
- File storage and basic models; no parsing yet.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 00 complete.

## Tasks
- `models/document.py` (SQLModel): id, filename, checksum, uploaded_at, status.
- `routers/files.py`: `POST /api/upload`, `GET /api/files`.
- `services/files.py`: size/type/checksum validation; secure filename; dedup.
- Frontend upload form (drag-and-drop + progress).

## API Endpoints (new/changed)
- `POST /api/upload` (multipart/form-data): returns Document JSON.
- `GET /api/files`: list of documents.

## Config & Flags
- `UPLOAD_DIR` with safe defaults; size caps; allowed mimetypes.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Uploads stored under `upload_objects_path/<doc_id>/`.
- DB row per document.

## Acceptance Criteria / Exit Gates
- Can upload/list; duplicate files deduped by checksum.

## Risks & Mitigations
- Large files; set size limit and streaming upload.

## Rollback
- Drop created tables; clear upload dir (scripted).
