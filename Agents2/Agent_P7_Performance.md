# P7 — Performance & Resilience — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Benchmark and optimize performance; implement limits and graceful degradation.

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

1) Add timers and memory sampling around parser stages.
2) Create benchmark scripts for 10/100/500-page docs; record p50/p95.
3) Introduce per-page parallelism (respect CPU quota) and timeouts.
4) Implement partial results policy with warnings when limits are hit.
5) Document tunables in config; add non-blocking perf job in CI.


## Expected Artifacts / Deliverables

- `bench/` scripts and reports
- Configurable limits for pages, OCR budget, and timeouts
- CI perf summary (non-blocking)


## Self‑Checks (Acceptance Tests)

- Meets target SLOs (e.g., ≤2s per 50 pages baseline).
- Parser degrades gracefully under heavy OCR or long docs.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
