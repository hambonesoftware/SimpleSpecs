# P2 — Design & Spikes — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Design the upgraded architecture and validate risky components with spikes before full implementation.

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

1) Author `docs/headers_design.md` covering: Reader, OCR path, Candidate extraction, Tree builder, Filters, Confidence scoring.
2) Spike 1: multi-column reading-order extraction (couple pages); save results under `spikes/reader/`.
3) Spike 2: numbering recognition library (Arabic/alpha/Roman/mixed); unit test in isolation.
4) Spike 3: OCR alignment (image-heavy page) and merge into span model.
5) Review with maintainers; annotate trade-offs and chosen defaults.


## Expected Artifacts / Deliverables

- `docs/headers_design.md`
- `spikes/reader/`, `spikes/numbering/`, `spikes/ocr/`
- Mini-test files demonstrating feasibility


## Self‑Checks (Acceptance Tests)

- Design approved with explicit reasons for each choice.
- Spikes show working code and limitations; issues filed for follow-ups.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
