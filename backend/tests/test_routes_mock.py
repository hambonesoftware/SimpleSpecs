"""Tests for mock API endpoints."""
from __future__ import annotations

from io import BytesIO
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.main import create_app

client = TestClient(create_app())


def test_routes_mock() -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    content = (
        "1. Introduction\n"
        "Intro line one.\n"
        "1.1 Scope\n"
        "Scope details.\n"
        "2. Details\n"
        "Detail line.\n"
    ).encode("utf-8")
    ingest = client.post(
        "/ingest",
        files={"file": ("sample.txt", BytesIO(content), "text/plain")},
    )
    assert ingest.status_code == 200
    ingest_payload = ingest.json()
    assert ingest_payload["status"] == "processed"
    assert "file_id" in ingest_payload

    file_id = ingest_payload["file_id"]
    parsed = client.get(f"/parsed/{file_id}")
    assert parsed.status_code == 200
    assert isinstance(parsed.json(), list) and parsed.json()

    headers = client.post(f"/headers/{file_id}/find")
    assert headers.status_code == 200
    header_payload = headers.json()
    assert header_payload["title"] == "Document"

    chunks = client.post(f"/chunks/{file_id}")
    assert chunks.status_code == 200
    chunk_payload = chunks.json()
    assert chunk_payload
    assert header_payload["section_id"] in chunk_payload

    persisted_chunks = client.get(f"/chunks/{file_id}")
    assert persisted_chunks.status_code == 200
    assert persisted_chunks.json() == chunk_payload

    specs = client.get(f"/specs/{file_id}")
    assert specs.status_code == 200
    assert len(specs.json()) >= 1
