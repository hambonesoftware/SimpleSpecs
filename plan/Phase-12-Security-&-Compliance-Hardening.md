# Phase 12 — Security & Compliance Hardening

## Objectives
- Strengthen default HTTP response headers for clickjacking, MIME sniffing, and referrer leakage.
- Ensure middleware-driven protections are test-covered.

## Scope
- Security headers middleware with configurable Content-Security-Policy (CSP).
- Regression tests validating header presence on representative API responses.

## Architecture/Stack
- Starlette `BaseHTTPMiddleware` stacked on FastAPI application.

## Dependencies
- Phase 11 complete so middleware ordering is defined.

## Tasks
- Implement `SecurityHeadersMiddleware` setting `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, and CSP.
- Register middleware after metrics collection to ensure headers decorate final responses.
- Add unit test asserting headers exist on `/api/health` responses.
- Document defaults within plan and agent instructions.

## API Endpoints (new/changed)
- No new endpoints; middleware augments responses globally.

## Config & Flags
- CSP string configurable via middleware constructor; default denies third-party origins.

## Prompts (if applicable)
_N/A_

## Artifacts & Deliverables
- Middleware implementation in `backend/middleware/security.py`.
- Tests in `tests/test_security_headers.py`.

## Acceptance Criteria / Exit Gates
- `/api/health` response includes all hardened headers with correct values.
- Test suite confirms middleware is active.

## Risks & Mitigations
- **Risk:** Overly strict CSP blocks static assets.
  - **Mitigation:** Default allows self-hosted resources; adjust in future if bundling external fonts/scripts.

## Rollback
- Remove middleware registration line from `backend/main.py` and delete middleware file.
