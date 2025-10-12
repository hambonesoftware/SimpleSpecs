# P6 — Tests & Golden Proofs — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Deliver a comprehensive test suite proving correctness, stability, and coverage.

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

1) Unit tests: numbering coverage, TOC suppression, running header/footer removal, level inference, gap healing.
2) Property tests: randomized page orders/column counts do not change final tree.
3) E2E golden tests: both PDFs match expected YAML/JSON trees.
4) Adversarial synthetic PDFs: Roman-only, alpha-only, no numbering, scanned multi-column.
5) Coverage: >90% for headers modules; enforce in CI.


## Expected Artifacts / Deliverables

- `tests/test_headers_numbering.py`, `tests/test_headers_filters.py`, `tests/test_headers_tree.py`
- `tests/expected/<pdf>.yaml` or `.json`
- Synthetic PDFs under `tests/assets/`
- Coverage report uploaded in CI


## Self‑Checks (Acceptance Tests)

- All tests green in CI; coverage threshold met.
- Golden outputs remain stable across runs.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
