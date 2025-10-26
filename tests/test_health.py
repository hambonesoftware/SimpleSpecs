from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    """The health endpoint should respond with a simple ok payload."""

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
