# P3 — Extraction Core (Reader) — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Implement a deterministic text+layout reader with optional OCR merge, producing normalized spans and reading order.

## Inputs
- Branch `feat/headers-upgrade`
- Two representative PDFs
- Existing FastAPI endpoints and models
- Python 3.12 environment

## Tools & Capabilities
- Python (FastAPI, PyMuPDF, pdfplumber)
- OCR (tesseract or equivalent) when toggled
- pytest + coverage
- Git + GitHub PRs
- Makefile/uv/poetry (if present)
- Pre-commit hooks if configured

## Constraints & Guardrails
- Keep `/api/headers` response schema unchanged.
- Deterministic outputs for identical inputs.
- Generate small, focused PRs with tests.
- Log decisions and produce artifacts.
- Prefer feature flags over breaking changes.

## Step-by-Step Plan

1) Create `backend/services/pdf_reader.py` with page blocks, spans, and ordered text flow; export as JSON for tests.
2) Column detection: x-cluster and left-edge ladders; block sort within columns; captions preserved, figures skipped.
3) Normalize hyphenation and ligatures; enforce Unicode NFC.
4) Add optional OCR path controlled by config (`headers.use_ocr`, `headers.ocr_engine`, `headers.ocr_threshold`).
5) Write unit tests for block sorting and normalization; add fixtures in `tests/fixtures/layout/`.


## Expected Artifacts / Deliverables

- `backend/services/pdf_reader.py`
- `tests/fixtures/layout/*.json`
- Unit tests covering reading order and normalization


## Self‑Checks (Acceptance Tests)

- Reader emits stable JSON across runs (order and content); tests pass.
- OCR merge preserves coordinates and does not duplicate spans.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
