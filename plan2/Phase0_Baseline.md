# Phase 0 — Baseline & Safety Net

## Objective
Freeze existing behavior and capture reproducible baselines.

## Key Tasks
1. Create branch `feat/headers-upgrade`.
2. Run app on sample PDFs, save current outputs to `tests/golden/before/`.
3. Implement CLI script for deterministic header runs.
4. Add DEBUG logs with per-page timing.

## Deliverables
- Golden 'before' JSON files
- `scripts/run_headers.py`
- CI replay job for regression detection

## Exit Criteria
- Golden artifacts committed and reproducible.
