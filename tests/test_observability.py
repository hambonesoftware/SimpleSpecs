"""Tests for observability endpoints and metrics."""

from __future__ import annotations

from backend.observability import metrics_registry


def test_metrics_endpoint_tracks_requests(client):
    metrics_registry.reset()
    response = client.get("/api/health")
    assert response.status_code == 200

    metrics_response = client.get("/api/metrics")
    assert metrics_response.status_code == 200
    payload = metrics_response.json()

    assert payload["requests_total"] >= 1
    assert payload["status_codes"]["2xx"] >= 1
    assert payload["routes"]["GET /api/health"]["count"] == 1


def test_status_endpoint_reports_database_and_version(client):
    metrics_registry.reset()
    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    payload = status_response.json()

    assert payload["database"]["ok"] is True
    assert payload["app"]["version"]
    assert "requests_total" in payload["metrics"]
