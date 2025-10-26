"""Smoke tests for the health endpoint located within the backend package."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ..main import app


def test_health_endpoint_returns_ok() -> None:
    """The `/api/health` route should return a JSON payload declaring success."""

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_health_request_id_header_is_sanitised() -> None:
    """Ensure the request-id middleware normalises identifiers for health responses."""

    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "  weird id "})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].strip() == response.headers["X-Request-ID"]
