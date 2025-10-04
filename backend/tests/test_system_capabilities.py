"""Tests for the system capabilities endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.main import create_app

client = TestClient(create_app())


def test_capabilities_endpoint() -> None:
    response = client.get("/system/capabilities")
    assert response.status_code == 200
    payload = response.json()

    for key in {"tesseract", "ghostscript", "java", "mineru_importable", "pdf_engine"}:
        assert key in payload

    assert isinstance(payload["mineru_importable"], bool)
    assert payload["pdf_engine"] in {"native", "mineru", "auto"}
