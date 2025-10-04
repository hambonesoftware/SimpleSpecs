from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


def _client(tmp_path):
    client = TestClient(create_app())
    return client


def test_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SIMPLS_MAX_FILE_MB", "1")
    get_settings.cache_clear()

    client = _client(tmp_path)

    # Successful upload
    response = client.post(
        "/ingest",
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 200
    file_id = response.json()["file_id"]

    # Retrieve parsed objects
    parsed = client.get(f"/parsed/{file_id}")
    assert parsed.status_code == 200
    assert isinstance(parsed.json(), list)

    # Unsupported media type
    response_bad_type = client.post(
        "/ingest",
        files={"file": ("image.png", io.BytesIO(b"data"), "image/png")},
    )
    assert response_bad_type.status_code == 415

    # Payload too large
    large_content = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response_large = client.post(
        "/ingest",
        files={"file": ("big.txt", large_content, "text/plain")},
    )
    assert response_large.status_code == 413
