# Phase 5 — Integration & API Parity

## Objective
Integrate new modules without changing API contracts.

## Key Tasks
1. Wire reader and detector in existing FastAPI router.
2. Add feature flags in `config.py`.
3. Support debug exports for dev mode.

## Deliverables
- Integrated backend
- Backward-compatible `/api/headers` endpoint

## Exit Criteria
- Old clients run unchanged; new toggles available.
