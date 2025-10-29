"""Tests covering CORS middleware behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ..main import app


ALLOWED_ORIGIN = "http://192.168.68.136:3600"


def test_successful_request_includes_cors_headers() -> None:
    """Successful requests should echo the requesting origin in CORS headers."""

    with TestClient(app) as client:
        response = client.options(
            "/api/files",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_error_responses_include_cors_headers(monkeypatch) -> None:
    """CORS headers should be present even when an endpoint raises an error."""

    def boom(*_args, **_kwargs):  # pragma: no cover - exercised via FastAPI
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.routers.files.list_documents", boom)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/files", headers={"Origin": ALLOWED_ORIGIN}
        )

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
