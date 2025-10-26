# Phase 11 — Observability & Telemetry

## Objectives
- Instrument the API for lightweight request telemetry.
- Expose metrics for operational insight and automated checks.

## Scope
- ASGI middleware for request timings and status counts.
- `/api/metrics` endpoint returning JSON payload (no Prometheus dependency).
- Tests verifying aggregation accuracy.

## Architecture/Stack
- Python 3.12, FastAPI, Starlette middleware.
- In-memory metrics registry guarded by threading locks.

## Dependencies
- Phase 10 complete and the FastAPI application bootstraps correctly.

## Tasks
- Create `MetricsRegistry` with counters for total requests, in-flight count, per-route latency stats, and status families.
- Add `RequestMetricsMiddleware` leveraging `perf_counter` to measure latency and record success/error codes.
- Mount middleware in `backend/main.py` after the request-id middleware.
- Add `/api/metrics` route returning the registry snapshot.
- Reset registry within tests to avoid cross-test contamination.
- Provide unit tests confirming metrics increment on health checks and that status families are populated.

## API Endpoints (new/changed)
- `GET /api/metrics`

## Config & Flags
- None required; metrics registry is in-process and zero-config.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Source modules in `backend/observability/`.
- Tests in `tests/test_observability.py`.
- Metrics documented in runbooks (see Phase 13).

## Acceptance Criteria / Exit Gates
- Calling `/api/health` followed by `/api/metrics` shows an incremented count for `GET /api/health`.
- Automated tests covering registry reset and snapshot accuracy pass.

## Risks & Mitigations
- **Risk:** Metrics growth leads to large in-memory state.
  - **Mitigation:** Track counts per route without storing payload bodies; registry can be reset via application restart.

## Rollback
- Remove middleware registration and delete the observability package; no persistent schema changes.
