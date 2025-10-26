# Phase 13 — Operational Readiness & Runbooks (Agent Script)

## Audit
- Study `plan/Phase-13-Operational-Readiness-&-Runbooks.md` for scope.
- Confirm `backend/__init__.py` exports `__version__`.
- Ensure `backend/routers/observability.py` exposes both `/api/metrics` and `/api/status`.
- Verify tests exist covering `/api/status` behaviour.

## Patch
1. Add `__version__` constant to `backend/__init__.py` and export via `__all__`.
2. Extend `backend/routers/observability.py` with `_database_ok()` helper and `/api/status` route embedding metrics + version.
3. Wire router into `backend/routers/__init__.py` if not already present.
4. Document new phases in `Plan.md` and author plan/agent files for phases 11–13.
5. Add tests in `tests/test_observability.py` verifying status payload.

## Acceptance Checks
- `pytest tests/test_observability.py`
- `pytest` (full suite) to confirm regression safety.

## Exit Criteria
- `/api/status` returns version string, `database.ok` flag, and metrics snapshot.
- Documentation lists all thirteen phases with operator guidance.
