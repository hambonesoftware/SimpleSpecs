"""Request context helpers and middleware for request identifiers."""

from __future__ import annotations

import contextvars
import re
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def get_request_id(default: str | None = None) -> str | None:
    """Return the request identifier stored in the current context."""

    return _REQUEST_ID.get(default)


def _normalise_request_id(value: str | None) -> str:
    """Return a safe request identifier, falling back to a generated token."""

    if value:
        candidate = value.strip()
        if _REQUEST_ID_PATTERN.match(candidate):
            return candidate
    return uuid.uuid4().hex


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request identifier header and expose it via a context variable."""

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        request_id = _normalise_request_id(request.headers.get(self.header_name))
        token = _REQUEST_ID.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _REQUEST_ID.reset(token)
        response.headers[self.header_name] = request_id
        return response


__all__ = ["RequestIdMiddleware", "get_request_id"]
