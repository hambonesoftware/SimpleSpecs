import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.config import get_settings
from backend.routers._headers_common import fetch_document_text


@pytest.fixture
def artifacts_dir(monkeypatch, tmp_path: Path) -> Path:
    """Configure the artifacts directory for tests using ``tmp_path``."""

    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        get_settings.cache_clear()


def test_fetch_document_text_uses_ingest_artifacts(artifacts_dir: Path) -> None:
    upload_id = "abc123"
    parsed_dir = artifacts_dir / upload_id / "parsed"
    parsed_dir.mkdir(parents=True)
    payload = [
        {"kind": "para", "text": "First line"},
        {"kind": "line", "text": "Second line"},
    ]
    (parsed_dir / "objects.json").write_text(json.dumps(payload))

    document = fetch_document_text(upload_id)

    assert "First line" in document
    assert "Second line" in document


def test_fetch_document_text_missing_upload(artifacts_dir: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        fetch_document_text("missing")

    assert exc.value.status_code == 404
