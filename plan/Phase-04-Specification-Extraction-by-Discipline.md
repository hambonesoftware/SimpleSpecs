# Phase 04 — Specification Extraction by Discipline

## Objectives
- Extract atomic spec lines and classify by Mechanical/Electrical/Controls/Software/PM.

## Scope
- Rule-based seed + LLM-assisted classification with standards priors.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phase 03 outline complete.

## Tasks
- Segment blocks under each header; split into atomic lines (bullets, numbered items).
- Rule pass: seed classification via term lexicons per department.
- LLM pass: classify ambiguous lines using fenced JSON output.
- Standards hardening: boost sections matching ASME/ISO/IEC terms.
- Store per-discipline JSON arrays with source header references.

## API Endpoints (new/changed)
- `POST /api/specs/extract/{doc_id}` → JSON buckets by discipline.

## Config & Flags
- Paths to `backend/resources/terms/*.json`; thresholds for rule vs LLM handoff.

## Prompts (if applicable)
- Department Classification (from Prompts-Library.md).

## Artifacts & Deliverables
- `specs.json` (department buckets) with provenance links.

## Acceptance Criteria / Exit Gates
- Classification F1 ≥ 0.90 baseline on samples.

## Risks & Mitigations
- Cross-discipline overlap; mitigated by tie-break rules and multi-label support for review.

## Rollback
- Use rules-only mode; log ambiguous to `Unknown` bucket.
