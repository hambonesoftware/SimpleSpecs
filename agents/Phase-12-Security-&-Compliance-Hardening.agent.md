# Phase 12 — Security & Compliance Hardening (Agent Script)

## Audit
- Review `plan/Phase-12-Security-&-Compliance-Hardening.md` for required headers.
- Ensure `backend/middleware/security.py` exists and exports `SecurityHeadersMiddleware`.
- Confirm middleware ordering in `backend/main.py` (request-id → metrics → security).
- Check for regression tests validating header presence.

## Patch
1. Implement `SecurityHeadersMiddleware` that applies hardened defaults (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, CSP).
2. Export middleware via `backend/middleware/__init__.py`.
3. Register middleware in `backend/main.py` after metrics middleware.
4. Add tests in `tests/test_security_headers.py` asserting headers exist on `/api/health`.

## Acceptance Checks
- `pytest tests/test_security_headers.py`

## Exit Criteria
- Hardened headers are present on API responses without duplicate definitions.
- Security tests pass.
