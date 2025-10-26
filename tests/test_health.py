from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    """The health endpoint should respond with a simple ok payload."""

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


def test_health_request_id_header_is_sanitised(client: TestClient) -> None:
    """Middleware should normalise inbound request ids before echoing them back."""

    response = client.get("/api/health", headers={"X-Request-ID": "  weird id "})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "  weird id "
    assert response.headers["X-Request-ID"].strip() == response.headers["X-Request-ID"]
