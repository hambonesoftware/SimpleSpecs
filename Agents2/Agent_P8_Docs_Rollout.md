# P8 — Docs & Rollout — Agent Operating Manual

## Role
You are the phase agent responsible for executing the tasks below with production rigor, without breaking public APIs.

## Objective
Finalize docs, create demos, and ship the release without breaking consumers.

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

1) Author `README-headers.md` with diagrams, config flags, and examples.
2) Provide `scripts/print_header_tree.py` as a demo CLI.
3) Update CHANGELOG; bump version; create release tag.
4) Merge `feat/headers-upgrade` to main via PR; attach before/after artifacts.
5) Announce changes with migration notes (none required for API consumers).


## Expected Artifacts / Deliverables

- `README-headers.md`
- Demo CLI script
- CHANGELOG entry and version tag
- PR with artifact screenshots/attachments


## Self‑Checks (Acceptance Tests)

- Docs let a new engineer reproduce results in ≤5 minutes.
- Release tag created and PR merged with approvals.


## Git & CI Etiquette
- Branch from `feat/headers-upgrade`.
- Commit messages: conventional (feat:, fix:, docs:, test:, refactor:).
- Open PRs with a checklist and artifact links.
- CI must pass (lint, type, tests) before merge.

## Handoff Notes
- Update the Overview with any deviations.
- Tag all artifacts with the phase and upload_id.
- Leave TODOs as GitHub issues if non-blocking.
