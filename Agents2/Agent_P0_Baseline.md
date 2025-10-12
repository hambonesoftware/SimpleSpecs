# P0 — Baseline & Safety Net — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Freeze behavior and capture reproducible 'before' outputs; set up CI replay to guard against regressions.

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

1) Create and push branch `feat/headers-upgrade`.
2) Run current app on the two PDFs; export:
   - Raw parsed objects
   - `/api/headers` responses
3) Store artifacts under `tests/golden/before/` and `tests/fixtures/layout/` if available.
4) Add `scripts/run_headers.py` to deterministically replay header extraction by `upload_id` or file path.
5) Add CI job to re-run replay on PRs; on failure, attach artifacts to the PR.
6) Enable structured DEBUG logs for parsing (per-page timings, column detection flags).


## Expected Artifacts / Deliverables

- `tests/golden/before/<pdf>.json`
- `scripts/run_headers.py`
- CI workflow step: golden replay
- README note on reproducing baselines


## Self‑Checks (Acceptance Tests)

- Baseline artifacts regenerate identical hashes across runs.
- CI replay passes on an unmodified main.
- The CLI works with both file path and upload_id inputs.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
