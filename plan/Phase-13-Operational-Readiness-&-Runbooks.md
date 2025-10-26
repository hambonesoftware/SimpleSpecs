# Phase 13 — Operational Readiness & Runbooks

## Objectives
- Provide a status endpoint aggregating runtime insights for runbooks.
- Document operational checks bridging metrics, versioning, and database health.

## Scope
- `/api/status` endpoint reusing metrics snapshot and probing database connectivity.
- Plan/agent updates outlining runbook steps for operators.

## Architecture/Stack
- FastAPI router extension leveraging SQLModel sessions for health probes.

## Dependencies
- Phase 11 metrics and Phase 12 security middleware registered.

## Tasks
- Introduce router under `backend/routers/observability.py` exposing `/api/status`.
- Implement `_database_ok()` helper executing `SELECT 1` via SQLModel session with exception handling.
- Embed application version sourced from `backend.__version__` into the response payload.
- Update `backend/__init__.py` to export `__version__` constant.
- Extend plan index to list new phases and provide operator notes.
- Add tests asserting `/api/status` returns version string, database ok flag, and metrics payload keys.

## API Endpoints (new/changed)
- `GET /api/status`

## Config & Flags
- None; relies on existing database configuration.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Router logic in `backend/routers/observability.py`.
- Tests in `tests/test_observability.py`.
- Updated `Plan.md` enumerating all phases.

## Acceptance Criteria / Exit Gates
- `/api/status` returns HTTP 200 with `{"database": {"ok": true}}` when SQLite is reachable.
- Response includes metrics summary and semantic version string.
- Automated tests pass.

## Risks & Mitigations
- **Risk:** Status endpoint reveals sensitive configuration.
  - **Mitigation:** Payload limited to boolean health indicators and version string.

## Rollback
- Remove `/api/status` route inclusion and delete helper functions; no data migrations involved.
