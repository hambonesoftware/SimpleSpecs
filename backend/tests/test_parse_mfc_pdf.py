"""Ensure the bundled MFC-5M PDF parses with the native engine."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


def test_mfc_pdf_upload(monkeypatch, tmp_path) -> None:
    """The ANSI/ASME MFC-5M sample should yield textual output."""

    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()

    try:
        client = TestClient(create_app())
        pdf_path = Path(__file__).resolve().parents[2] / "MFC-5M_R2001_E1985.pdf"

        with pdf_path.open("rb") as handle:
            files = {"file": (pdf_path.name, handle, "application/pdf")}
            response = client.post("/ingest", files=files, data={"engine": "native"})

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "processed"
        assert payload["object_count"] >= 1

        parsed = client.get(f"/parsed/{payload['file_id']}")
        assert parsed.status_code == 200, parsed.text
        objects = parsed.json()
        assert len(objects) == payload["object_count"]

        first_text = next((obj["text"] for obj in objects if obj.get("text")), None)
        assert first_text is not None
        assert "Measurement of Liquid Flow" in first_text
    finally:
        get_settings.cache_clear()
