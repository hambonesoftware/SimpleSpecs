"""Ensure frontend API helpers map to available backend routes."""

from __future__ import annotations

from backend.main import app


EXPECTED_FRONTEND_ROUTES = {
    ("GET", "/api/files"),
    ("POST", "/api/upload"),
    ("DELETE", "/api/files/{document_id}"),
    ("POST", "/api/parse/{document_id}"),
    ("POST", "/api/headers/{document_id}"),
    ("POST", "/api/specs/extract/{document_id}"),
    ("POST", "/api/specs/compare/{document_id}"),
    ("GET", "/api/specs/{document_id}"),
    ("POST", "/api/specs/{document_id}/approve"),
    ("GET", "/api/specs/{document_id}/export"),
}


def test_frontend_functions_have_matching_routes() -> None:
    """The backend should expose every route used by the frontend API module."""

    observed_routes = set()
    for route in app.routes:
        if not getattr(route, "methods", None):
            continue
        for method in route.methods:
            observed_routes.add((method, route.path))

    missing = EXPECTED_FRONTEND_ROUTES - observed_routes
    assert not missing, f"Frontend API routes missing from backend: {sorted(missing)}"
