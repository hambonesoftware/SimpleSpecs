"""Tests for the simplified LLM header extraction pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, init_db
from backend.models import Document
from backend.services import openrouter_client
from backend.services.artifact_store import persist_parse_result
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult
from backend.main import app


def _write_lines(export_dir: Path, document_id: int) -> None:
    lines_dir = export_dir / str(document_id)
    lines_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {"page": 1, "line_in_page": 1, "text": "Introduction"},
        {"page": 1, "line_in_page": 2, "text": "Overview of the system"},
        {"page": 2, "line_in_page": 1, "text": "Scope"},
    ]
    with (lines_dir / "lines.jsonl").open("w", encoding="utf-8") as handle:
        for entry in payload:
            handle.write(json.dumps(entry))
            handle.write("\n")


def test_headers_endpoint_records_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEADERS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HEADERS_MODE", "llm_simple")
    monkeypatch.setenv("HEADERS_LLM_STRICT", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    reset_settings_cache()

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        document = Document(filename="sample.pdf", checksum="checksum-headers")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

    settings = get_settings()
    _write_lines(settings.export_dir, document_id)

    response_payload = {
        "headers": [
            {"title": "Introduction", "level": 1, "page": 1},
            {"title": "Scope", "level": 2, "page": 2},
        ]
    }

    monkeypatch.setattr(
        openrouter_client,
        "chat",
        lambda *_, **__: json.dumps(response_payload),
    )

    with TestClient(app) as client:
        response = client.post(f"/api/headers/{document_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["llm_headers"] == response_payload["headers"]
    assert any(match["found"] for match in data["matches"])

    log_dir = tmp_path / "logs"
    raw_log = log_dir / f"headers_{document_id}_llm.json"
    match_log = log_dir / f"header_matches_{document_id}.jsonl"
    assert raw_log.exists()
    assert match_log.exists()

    stored = json.loads(raw_log.read_text(encoding="utf-8"))
    assert stored == response_payload
    match_lines = match_log.read_text(encoding="utf-8").strip().splitlines()
    assert match_lines, "match log should contain at least one entry"


def test_headers_endpoint_strict_invalid_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEADERS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HEADERS_MODE", "llm_simple")
    monkeypatch.setenv("HEADERS_LLM_STRICT", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    reset_settings_cache()

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        document = Document(filename="sample.pdf", checksum="checksum-strict")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

    settings = get_settings()
    _write_lines(settings.export_dir, document_id)

    monkeypatch.setattr(
        openrouter_client,
        "chat",
        lambda *_, **__: "not-json",
    )

    with TestClient(app) as client:
        response = client.post(f"/api/headers/{document_id}")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_llm_json"}

    log_dir = tmp_path / "logs"
    raw_log = log_dir / f"headers_{document_id}_llm.json"
    assert raw_log.exists()
    assert raw_log.read_text(encoding="utf-8") == "not-json"


def test_headers_endpoint_uses_document_pages_when_lines_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HEADERS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HEADERS_MODE", "llm_simple")
    monkeypatch.setenv("HEADERS_LLM_STRICT", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    reset_settings_cache()

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        document = Document(filename="sample.pdf", checksum="checksum-pages")
        session.add(document)
        session.commit()
        session.refresh(document)

        parse_result = ParseResult(
            pages=[
                ParsedPage(
                    page_number=1,
                    width=612.0,
                    height=792.0,
                    blocks=[
                        ParsedBlock(
                            text="Introduction",
                            bbox=(0.0, 0.0, 100.0, 24.0),
                        ),
                        ParsedBlock(
                            text="Overview of the system",
                            bbox=(0.0, 24.0, 100.0, 48.0),
                        ),
                    ],
                ),
                ParsedPage(
                    page_number=2,
                    width=612.0,
                    height=792.0,
                    blocks=[
                        ParsedBlock(
                            text="Scope",
                            bbox=(0.0, 0.0, 100.0, 24.0),
                        )
                    ],
                ),
            ]
        )

        persist_parse_result(
            session=session, document=document, parse_result=parse_result
        )
        document_id = int(document.id or 0)

    settings = get_settings()
    export_lines = settings.export_dir / str(document_id) / "lines.jsonl"
    if export_lines.exists():
        export_lines.unlink()

    response_payload = {
        "headers": [
            {"title": "Introduction", "level": 1, "page": 1},
            {"title": "Scope", "level": 2, "page": 2},
        ]
    }

    monkeypatch.setattr(
        openrouter_client,
        "chat",
        lambda *_, **__: json.dumps(response_payload),
    )

    with TestClient(app) as client:
        response = client.post(f"/api/headers/{document_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["llm_headers"] == response_payload["headers"]
    assert any(match["found"] for match in data["matches"])

    log_dir = tmp_path / "logs"
    raw_log = log_dir / f"headers_{document_id}_llm.json"
    match_log = log_dir / f"header_matches_{document_id}.jsonl"
    assert raw_log.exists()
    assert match_log.exists()
    assert not export_lines.exists()
