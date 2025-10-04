"""Tests for ingesting the bundled EPF, Co. PDF document."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


def test_epf_co_pdf_upload(monkeypatch, tmp_path) -> None:
    """Ensure the EPF, Co. sample PDF uploads and parses successfully."""

    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()

    try:
        client = TestClient(create_app())
        pdf_path = Path(__file__).resolve().parents[2] / "Epf, Co.pdf"

        with pdf_path.open("rb") as handle:
            files = {"file": (pdf_path.name, handle, "application/pdf")}
            response = client.post("/ingest", files=files)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "processed"
        assert payload["object_count"] > 0

        parsed = client.get(f"/parsed/{payload['file_id']}")
        assert parsed.status_code == 200, parsed.text
        objects = parsed.json()
        assert len(objects) == payload["object_count"]

        first_text = next(
            (obj["text"] for obj in objects if obj.get("text")),
            None,
        )
        assert first_text is not None and "Request for Quotation" in first_text
        assert any("EPF, Co." in (obj.get("text") or "") for obj in objects)
    finally:
        get_settings.cache_clear()
