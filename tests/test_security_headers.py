"""Ensure security middleware applies hardened headers."""

from __future__ import annotations


def test_security_headers_present(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "geolocation=()" in headers["Permissions-Policy"]
    assert "Strict-Transport-Security" in headers
    assert "Content-Security-Policy" in headers
