# Phase 02 — Native PDF Parsing Engine

## Objectives
- Reliable text block extraction with multi-column support and OCR fallback.

## Scope
- Implement `pdf_native.py` with block/line extraction and TOC/header/footer suppression.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 01 complete.

## Tasks
- Implement page iterator using PyMuPDF; collect blocks with bbox and font metrics.
- Integrate pdfplumber for cross-validation of text lines.
- Add TOC detection (keywords + density near early pages) and suppress.
- Detect running headers/footers via repeating region heuristics; suppress.
- Optional Camelot table detection; attach table markers (no parsing into cells yet).
- OCR fallback (pytesseract) when no extractable text per page.
- MinerU fallback pipeline for image-heavy docs (flag‑gated).

## API Endpoints (new/changed)
- `POST /api/parse/{doc_id}` → returns `{ pages, blocks, images, tables? }`.

## Config & Flags
- `PARSER_MULTI_COLUMN`, `PARSER_ENABLE_OCR`, `HEADERS_SUPPRESS_TOC`, `HEADERS_SUPPRESS_RUNNING`, `MINERU_FALLBACK`.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- JSON parse artifact stored per document (cache).

## Acceptance Criteria / Exit Gates
- Non-empty parsed objects for both EPF and MFC samples.
- Re-run stable across seeds (idempotent).

## Risks & Mitigations
- False TOC suppression; mitigate by threshold + page index limits.

## Rollback
- Disable suppression flags; fall back to raw blocks.
