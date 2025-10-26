"""Tests covering document upload functionality."""

from __future__ import annotations

import io
import os
from pathlib import Path

from fastapi.testclient import TestClient

PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


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
    stored_path = (
        Path(os.environ["UPLOAD_DIR"]) / str(document_id) / payload["filename"]
    )
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


def test_delete_document_removes_artifacts(client: TestClient) -> None:
    """Deleting a document should remove database records and stored files."""

    response = _post_pdf(client, PDF_BYTES, filename="delete-me.pdf")
    assert response.status_code == 201
    payload = response.json()
    document_id = payload["id"]

    upload_path = (
        Path(os.environ["UPLOAD_DIR"]) / str(document_id) / payload["filename"]
    )
    assert upload_path.exists()

    delete_response = client.delete(f"/api/files/{document_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    assert not upload_path.exists()

    list_response = client.get("/api/files")
    assert list_response.status_code == 200
    remaining_ids = {item["id"] for item in list_response.json()}
    assert document_id not in remaining_ids

    second_delete = client.delete(f"/api/files/{document_id}")
    assert second_delete.status_code == 404
    assert second_delete.json()["detail"] == "Document not found"
