# P5 — Integration & API Parity — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Integrate new reader and detector behind the existing router, preserving the public API and adding feature flags.

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

1) Keep `/api/headers` contract; add optional flags: `use_ocr`, `aggressive_toc_filter`, `return_confidence` (default off).
2) Wire modules; ensure env/config toggles are documented in `backend/config.py`.
3) Add debug artifact export under `/debug/headers/<upload_id>/...` gated by `DEBUG_HEADERS=1` env.
4) Add integration tests to confirm old clients still work unchanged.


## Expected Artifacts / Deliverables

- Updated router wiring
- Config flags and docs
- Integration tests


## Self‑Checks (Acceptance Tests)

- Legacy clients function without changes.
- New flags toggle behavior deterministically.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
