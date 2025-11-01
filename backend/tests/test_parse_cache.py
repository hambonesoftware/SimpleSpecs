import importlib
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import Session, select

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, reset_database_state
from backend.models import Document, DocumentArtifact
from backend.services.pdf_native import (
    ParsedBlock,
    ParsedPage,
    ParsedTable,
    ParseResult,
)


def _reload_app_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "app.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))

    reset_settings_cache()
    reset_database_state()

    import backend.paths as paths

    importlib.reload(paths)
    import backend.main as main

    importlib.reload(main)


def _create_document(session: Session) -> Document:
    document = Document(filename="doc.pdf", checksum="cache-checksum")
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _stub_parse_factory(counter: list[int]) -> Callable:
    def _stub_parse(document_path, *, settings):  # noqa: ANN001 - FastAPI dependency signature
        counter[0] += 1
        block = ParsedBlock(
            text="Heading",
            bbox=(0.0, 0.0, 10.0, 5.0),
            font="Arial",
            font_size=12.0,
            source="pymupdf",
        )
        table = ParsedTable(
            page_number=0,
            bbox=(1.0, 1.0, 4.0, 4.0),
            flavor="stream",
            accuracy=0.9,
        )
        page = ParsedPage(
            page_number=0,
            width=612.0,
            height=792.0,
            blocks=[block],
            tables=[table],
            is_toc=True,
        )
        return ParseResult(pages=[page], has_ocr=True, used_mineru=False)

    return _stub_parse


@pytest.mark.usefixtures("tmp_path")
def test_parse_document_reuses_cached_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_app_environment(tmp_path, monkeypatch)

    from backend.main import app

    parse_calls = [0]
    monkeypatch.setattr(
        "backend.routers.parse.parse_pdf",
        _stub_parse_factory(parse_calls),
    )

    settings = get_settings()

    try:
        with TestClient(app) as client:
            engine = get_engine()
            with Session(engine) as session:
                document = _create_document(session)
                document_id = document.id

            assert document_id is not None
            document_dir = settings.upload_dir / str(document_id)
            document_dir.mkdir(parents=True, exist_ok=True)
            (document_dir / "doc.pdf").write_bytes(b"PDF")

            response_first = client.post(f"/api/parse/{document_id}")
            assert response_first.status_code == 200
            assert parse_calls[0] == 1

            response_second = client.post(f"/api/parse/{document_id}")
            assert response_second.status_code == 200
            assert parse_calls[0] == 1

            payload = response_second.json()
            assert payload["has_ocr"] is True
            assert payload["pages"][0]["is_toc"] is True
            assert payload["pages"][0]["blocks"][0]["text"] == "Heading"
    finally:
        reset_settings_cache()
        reset_database_state()


@pytest.mark.usefixtures("tmp_path")
def test_parse_document_rehydrates_from_stored_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_app_environment(tmp_path, monkeypatch)

    from backend.main import app

    parse_calls = [0]
    monkeypatch.setattr(
        "backend.routers.parse.parse_pdf",
        _stub_parse_factory(parse_calls),
    )

    settings = get_settings()

    try:
        with TestClient(app) as client:
            engine = get_engine()
            with Session(engine) as session:
                document = _create_document(session)
                document_id = document.id

            assert document_id is not None
            document_dir = settings.upload_dir / str(document_id)
            document_dir.mkdir(parents=True, exist_ok=True)
            (document_dir / "doc.pdf").write_bytes(b"PDF")

            response_first = client.post(f"/api/parse/{document_id}")
            assert response_first.status_code == 200
            assert parse_calls[0] == 1

            with Session(engine) as session:
                session.exec(delete(DocumentArtifact))
                session.commit()

            response_second = client.post(f"/api/parse/{document_id}")
            assert response_second.status_code == 200
            assert parse_calls[0] == 1

            payload = response_second.json()
            assert payload["used_mineru"] is False
            assert payload["pages"][0]["tables"][0]["flavor"] == "stream"
            assert payload["pages"][0]["is_toc"] is True

            with Session(engine) as session:
                artifacts = session.exec(select(DocumentArtifact)).all()
                assert len(artifacts) == 1
    finally:
        reset_settings_cache()
        reset_database_state()
