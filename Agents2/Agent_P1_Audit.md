# P1 — Audit & Gap Matrix — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Audit the current pipeline and enumerate missing best practices (layout, numbering, typography, TOC suppression, OCR fallback).

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

1) Instrument span capture: font family/size/weight, bold/ALLCAPS flags, x/y boxes, page block id.
2) Detect and export multi-column segmentation and reading-order traces (x-clusters, block sort order).
3) Compare outputs against the PDFs to identify missing headers/subheaders.
4) Draft `docs/headers_gap_matrix.md` and mark each practice: Present / Partial / Missing; include page examples.
5) Propose minimal instrumentation hooks for later debugging (env flags, dump JSON toggles).


## Expected Artifacts / Deliverables

- `docs/headers_gap_matrix.md` with examples and screenshots if allowed
- Updated debug toggles (env/config) documented


## Self‑Checks (Acceptance Tests)

- Gap Matrix covers numbering patterns (Arabic/alpha/Roman), TOC/RH/footers, OCR cases, hyphen/ligature repair.
- Each 'Missing' item references observed evidence in the PDFs.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
