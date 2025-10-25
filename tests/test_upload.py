"""Tests covering document upload functionality."""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.config import reset_settings_cache
from backend.database import reset_database_state

PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    """Provide isolated database and upload directories per test."""

    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("MAX_UPLOAD_SIZE", str(1024))
    reset_settings_cache()
    reset_database_state()
    yield
    reset_settings_cache()
    reset_database_state()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a test client for the FastAPI application."""

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


def _post_pdf(client: TestClient, content: bytes, filename: str = "sample.pdf"):
    return client.post(
        "/api/upload",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )


def test_upload_creates_document_and_persists_file(client: TestClient) -> None:
    """Uploading a PDF should create a document entry and save the file on disk."""

    response = _post_pdf(client, PDF_BYTES)
    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "sample.pdf"
    assert "checksum" in payload
    assert "uploaded_at" in payload

    document_id = payload["id"]
    stored_path = Path(os.environ["UPLOAD_DIR"]) / str(document_id) / payload["filename"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == PDF_BYTES

    list_response = client.get("/api/files")
    assert list_response.status_code == 200
    documents = list_response.json()
    assert any(doc["id"] == document_id for doc in documents)


def test_duplicate_upload_returns_existing_document(client: TestClient) -> None:
    """Uploading the same file twice should reuse the original document record."""

    first = _post_pdf(client, PDF_BYTES)
    assert first.status_code == 201
    first_payload = first.json()

    second = _post_pdf(client, PDF_BYTES)
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_payload["id"]


def test_large_file_is_rejected(client: TestClient) -> None:
    """Files exceeding the configured size limit should be rejected."""

    oversized_content = PDF_BYTES + b"A" * 1500
    response = _post_pdf(client, oversized_content, filename="large.pdf")
    assert response.status_code == 413
    payload = response.json()
    assert payload["detail"] == "File exceeds maximum allowed size"

    upload_dir = Path(os.environ["UPLOAD_DIR"])
    assert not any(upload_dir.rglob("large.pdf"))
