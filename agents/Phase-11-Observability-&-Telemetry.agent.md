# Phase 11 — Observability & Telemetry (Agent Script)

## Audit
- Inspect `plan/Phase-11-Observability-&-Telemetry.md` for scope and acceptance criteria.
- Confirm `backend/observability/` package exists with registry and middleware modules.
- Verify `backend/main.py` registers `RequestMetricsMiddleware` after the request-id middleware.
- Check `/api/metrics` route is included via `backend/routers/observability.py`.

## Patch
1. Create or update `backend/observability/metrics.py` with a thread-safe `MetricsRegistry` and `RequestMetricsMiddleware`.
2. Export the registry from `backend/observability/__init__.py`.
3. Register the middleware in `backend/main.py`.
4. Add `/api/metrics` route and ensure it is wired in `backend/routers/__init__.py`.
5. Reset the registry in `tests/conftest.py` and add unit tests under `tests/test_observability.py`.

## Acceptance Checks
- `pytest tests/test_observability.py`
- `pytest` (full suite) — optional but recommended.

## Exit Criteria
- Metrics endpoint reports counts for at least one routed request.
- Tests covering registry behaviour and endpoint response pass.
