"""Smoke tests for service health and CORS configuration."""

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


def test_health_endpoint_allows_configured_origin(monkeypatch) -> None:
    """The /health endpoint should respond with the configured CORS origin."""

    monkeypatch.setenv("SIMPLS_ALLOW_ORIGINS", "http://example.com")
    get_settings.cache_clear()

    client = TestClient(create_app())

    response = client.get("/health", headers={"Origin": "http://example.com"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == "http://example.com"


def test_health_endpoint_rejects_unconfigured_origin(monkeypatch) -> None:
    """Non-configured origins should not receive CORS headers."""

    monkeypatch.setenv("SIMPLS_ALLOW_ORIGINS", "http://allowed.test")
    get_settings.cache_clear()

    client = TestClient(create_app())

    response = client.get("/health", headers={"Origin": "http://other.test"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
