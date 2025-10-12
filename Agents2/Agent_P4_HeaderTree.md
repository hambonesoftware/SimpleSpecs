# P4 — Header Detector & Tree Builder — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Build the candidate detector and hierarchical tree builder with robust filters and confidence scoring.

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

1) Create `backend/services/headers_detect.py`.
2) Candidate extraction:
   - Regex patterns: `^\d+(?:\.\d+)*`, `^[A-Z](?:\.\d+)*`, Roman numerals, `(Annex|Appendix) [A-Z]`.
   - Typographic cues: size rank (z-score), bold, caps, indent, top-of-page prior.
3) Filters:
   - TOC/Index/Glossary pages (leaders, page-number columns, known titles).
   - Running headers/footers and page numbers (margin bands; repeated ≥60%).
4) Tree building:
   - Infer level from numbering depth; fallback to typography when numbering missing.
   - Gap‑healing: create virtual nodes when hierarchy jumps are detected.
   - De-duplication across page breaks; cross-page continuity.
5) Confidence score with reasons (keep for debug only unless flag enabled).
6) Unit & golden tests to ensure nested completeness on both PDFs.


## Expected Artifacts / Deliverables

- `backend/services/headers_detect.py`
- Confidence metadata (optional in API)
- Golden 'after' trees in `tests/golden/after/`


## Self‑Checks (Acceptance Tests)

- Trees match hand-annotated expectations; TOC/running header noise is suppressed.
- All numbering schemas are recognized; mixed typography handled.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
