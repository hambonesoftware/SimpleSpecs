"""Security related middleware for HTTP responses."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a hardened set of default security headers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        content_security_policy: str
        | None = "default-src 'self'; frame-ancestors 'none'; form-action 'self'",
    ) -> None:
        super().__init__(app)
        self._content_security_policy = content_security_policy

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), fullscreen=()",
        )
        headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
        if self._content_security_policy:
            headers.setdefault("Content-Security-Policy", self._content_security_policy)
        return response


__all__ = ["SecurityHeadersMiddleware"]
