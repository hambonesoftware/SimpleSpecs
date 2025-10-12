# Phase 3 — Extraction Core (Reader)

## Objective
Develop the text+layout reader with OCR fallback.

## Key Tasks
1. Implement `backend/services/pdf_reader.py`.
2. Support page blocks, reading order, and normalization.
3. Add OCR merge logic and config toggles (`use_ocr`, `ocr_engine`).

## Deliverables
- Reader module
- Page layout fixtures

## Exit Criteria
- Deterministic layout JSON outputs for sample PDFs.
