"""Tests for document header cache hydration behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, init_db, reset_database_state
from backend.main import app
from backend.models import (
    Document,
    DocumentArtifact,
    DocumentArtifactType,
    DocumentSection,
)
from backend.services.simpleheaders_state import SimpleHeadersState


def test_cached_headers_hydrates_section_state(monkeypatch, tmp_path) -> None:
    """Fetching cached headers should hydrate the section text cache."""

    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("EXPORT_RETENTION_DAYS", "1")
    monkeypatch.setenv("MAX_UPLOAD_SIZE", "1024")

    reset_settings_cache()
    reset_database_state()
    settings = get_settings()
    init_db()

    engine = get_engine()
    SimpleHeadersState.clear()

    with Session(engine) as session:
        document = Document(filename="doc.pdf", checksum="abc123")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

        section = DocumentSection(
            document_id=document_id,
            section_key="intro",
            title="Intro",
            number="1",
            level=1,
            start_global_idx=2,
            end_global_idx=4,
            start_page=0,
            end_page=0,
        )
        session.add(section)

        artifact = DocumentArtifact(
            document_id=document_id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            artifact_key="llm_full",
            sha_inputs="inputs",
            body={
                "headers": [
                    {"text": "Intro", "number": "1", "level": 1, "global_idx": 2}
                ],
                "sections": [
                    {
                        "section_key": "intro",
                        "title": "Intro",
                        "number": "1",
                        "level": 1,
                        "start_global_idx": 2,
                        "end_global_idx": 4,
                        "start_page": 0,
                        "end_page": 0,
                    }
                ],
                "doc_hash": "artifact-hash",
            },
        )
        session.add(artifact)
        session.commit()

    doc_dir = settings.upload_dir / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    lines = [
        {"global_idx": 2, "text": "Intro heading"},
        {"global_idx": 3, "text": "Body text"},
    ]

    def _fake_collect_line_metrics(
        document_bytes: bytes,
        metadata: dict | None,
        *,
        suppress_toc: bool,
        suppress_running: bool,
        tracer,
    ):
        return lines, set(), "artifact-hash"

    monkeypatch.setattr(
        "backend.routers.documents.collect_line_metrics",
        _fake_collect_line_metrics,
    )

    with TestClient(app) as client:
        response = client.get(f"/api/documents/{document_id}/headers")
        assert response.status_code == 200
        cached = SimpleHeadersState.get(document_id)
        assert cached is not None
        cached_hash, cached_lines = cached
        assert cached_hash == "artifact-hash"
        assert cached_lines == lines

        section_response = client.get(
            f"/api/headers/{document_id}/section-text",
            params={"start": 2, "end": 3},
        )

    SimpleHeadersState.clear(document_id)

    assert section_response.status_code == 200
    assert section_response.text == "Intro heading\nBody text"
