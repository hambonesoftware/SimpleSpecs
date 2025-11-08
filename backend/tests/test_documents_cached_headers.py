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


def _prepare_runtime(monkeypatch, tmp_path):
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
    return settings, engine


def test_cached_headers_hydrates_section_state(monkeypatch, tmp_path) -> None:
    """Fetching cached headers should hydrate the section text cache."""

    settings, engine = _prepare_runtime(monkeypatch, tmp_path)

    with Session(engine) as session:
        document = Document(filename="doc.pdf", checksum="abc123")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

        session.add(
            DocumentSection(
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
        )

        lines = [
            {"global_idx": 2, "text": "Intro heading"},
            {"global_idx": 3, "text": "Body text"},
        ]

        session.add(
            DocumentArtifact(
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
                    "lines": lines,
                },
            )
        )
        session.commit()

    doc_dir = settings.upload_dir / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    def _unexpected_collect_line_metrics(
        document_bytes: bytes,
        metadata: dict | None,
        *,
        suppress_toc: bool,
        suppress_running: bool,
        tracer,
    ):
        raise AssertionError("collect_line_metrics should not run when lines are stored")

    monkeypatch.setattr(
        "backend.routers.documents.collect_line_metrics",
        _unexpected_collect_line_metrics,
    )

    with TestClient(app) as client:
        response = client.get(f"/api/documents/{document_id}/headers")
        assert response.status_code == 200
        cached = SimpleHeadersState.get(document_id)
        assert cached is not None
        cached_hash, cached_lines = cached
        assert cached_hash == "artifact-hash"
        assert cached_lines == lines

        payload = response.json()
        assert payload["headers"] == [
            {"text": "Intro", "number": "1", "level": 1, "global_idx": 2}
        ]
        assert payload["sections"][0]["section_key"] == "intro"

        section_response = client.get(
            f"/api/headers/{document_id}/section-text",
            params={"start": 2, "end": 3},
        )

    SimpleHeadersState.clear(document_id)

    assert section_response.status_code == 200
    assert section_response.text == "Intro heading\nBody text"


def test_cached_headers_fallbacks_when_lines_missing(monkeypatch, tmp_path) -> None:
    """Artifacts without stored lines should trigger PDF rehydration."""

    settings, engine = _prepare_runtime(monkeypatch, tmp_path)

    with Session(engine) as session:
        document = Document(filename="doc.pdf", checksum="fallback")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

        session.add(
            DocumentSection(
                document_id=document_id,
                section_key="fallback-intro",
                title="Fallback Intro",
                number="1",
                level=1,
                start_global_idx=10,
                end_global_idx=12,
                start_page=0,
                end_page=0,
            )
        )

        session.add(
            DocumentArtifact(
                document_id=document_id,
                artifact_type=DocumentArtifactType.HEADER_TREE,
                artifact_key="llm_full",
                sha_inputs="inputs-fallback",
                body={
                    "headers": [
                        {
                            "text": "Fallback Intro",
                            "number": "1",
                            "level": 1,
                            "global_idx": 10,
                        }
                    ],
                    "sections": [
                        {
                            "section_key": "fallback-intro",
                            "title": "Fallback Intro",
                            "number": "1",
                            "level": 1,
                            "start_global_idx": 10,
                            "end_global_idx": 12,
                            "start_page": 0,
                            "end_page": 0,
                        }
                    ],
                    "doc_hash": "rehydrate",
                },
            )
        )
        session.commit()

    doc_dir = settings.upload_dir / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    lines = [
        {"global_idx": 10, "text": "Fallback heading"},
        {"global_idx": 11, "text": "Fallback body"},
    ]
    calls: list[int] = []

    def _fake_collect_line_metrics(
        document_bytes: bytes,
        metadata: dict | None,
        *,
        suppress_toc: bool,
        suppress_running: bool,
        tracer,
    ):
        calls.append(int(metadata["document_id"]))
        return lines, set(), "rehydrate"

    monkeypatch.setattr(
        "backend.routers.documents.collect_line_metrics",
        _fake_collect_line_metrics,
    )

    with TestClient(app) as client:
        response = client.get(f"/api/documents/{document_id}/headers")
        assert response.status_code == 200

    assert calls == [document_id]
    cached = SimpleHeadersState.get(document_id)
    assert cached is not None
    assert cached[0] == "rehydrate"
    assert cached[1] == lines

    SimpleHeadersState.clear()


def test_cached_headers_recall_across_documents(monkeypatch, tmp_path) -> None:
    """Switching between documents should preserve and rehydrate cached headers."""

    settings, engine = _prepare_runtime(monkeypatch, tmp_path)

    with Session(engine) as session:
        document_a = Document(filename="doc-a.pdf", checksum="checksum-a")
        document_b = Document(filename="doc-b.pdf", checksum="checksum-b")
        session.add(document_a)
        session.add(document_b)
        session.commit()
        session.refresh(document_a)
        session.refresh(document_b)

        doc_a_id = int(document_a.id or 0)
        doc_b_id = int(document_b.id or 0)

        session.add(
            DocumentSection(
                document_id=doc_a_id,
                section_key="a-intro",
                title="Doc A Intro",
                number="1",
                level=1,
                start_global_idx=1,
                end_global_idx=2,
                start_page=0,
                end_page=0,
            )
        )
        session.add(
            DocumentSection(
                document_id=doc_b_id,
                section_key="b-intro",
                title="Doc B Intro",
                number="1",
                level=1,
                start_global_idx=5,
                end_global_idx=6,
                start_page=0,
                end_page=0,
            )
        )

        lines_by_doc = {
            doc_a_id: [
                {"global_idx": 1, "text": "Doc A Heading"},
                {"global_idx": 2, "text": "Doc A Body"},
            ],
            doc_b_id: [
                {"global_idx": 5, "text": "Doc B Heading"},
                {"global_idx": 6, "text": "Doc B Body"},
            ],
        }

        session.add(
            DocumentArtifact(
                document_id=doc_a_id,
                artifact_type=DocumentArtifactType.HEADER_TREE,
                artifact_key="llm_full",
                sha_inputs="inputs-a",
                body={
                    "headers": [
                        {"text": "Doc A Intro", "number": "1", "level": 1, "global_idx": 1}
                    ],
                    "sections": [
                        {
                            "section_key": "a-intro",
                            "title": "Doc A Intro",
                            "number": "1",
                            "level": 1,
                            "start_global_idx": 1,
                            "end_global_idx": 2,
                            "start_page": 0,
                            "end_page": 0,
                        }
                    ],
                    "doc_hash": "hash-a",
                    "lines": lines_by_doc[doc_a_id],
                },
            )
        )
        session.add(
            DocumentArtifact(
                document_id=doc_b_id,
                artifact_type=DocumentArtifactType.HEADER_TREE,
                artifact_key="llm_full",
                sha_inputs="inputs-b",
                body={
                    "headers": [
                        {"text": "Doc B Intro", "number": "1", "level": 1, "global_idx": 5}
                    ],
                    "sections": [
                        {
                            "section_key": "b-intro",
                            "title": "Doc B Intro",
                            "number": "1",
                            "level": 1,
                            "start_global_idx": 5,
                            "end_global_idx": 6,
                            "start_page": 0,
                            "end_page": 0,
                        }
                    ],
                    "doc_hash": "hash-b",
                    "lines": lines_by_doc[doc_b_id],
                },
            )
        )
        session.commit()

    doc_a_dir = settings.upload_dir / str(doc_a_id)
    doc_b_dir = settings.upload_dir / str(doc_b_id)
    doc_a_dir.mkdir(parents=True, exist_ok=True)
    doc_b_dir.mkdir(parents=True, exist_ok=True)
    (doc_a_dir / "doc-a.pdf").write_bytes(b"%PDF-1.4\n%EOF")
    (doc_b_dir / "doc-b.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    def _unexpected_collect_line_metrics(
        document_bytes: bytes,
        metadata: dict | None,
        *,
        suppress_toc: bool,
        suppress_running: bool,
        tracer,
    ):
        raise AssertionError("collect_line_metrics should not run when lines are stored")

    monkeypatch.setattr(
        "backend.routers.documents.collect_line_metrics",
        _unexpected_collect_line_metrics,
    )

    with TestClient(app) as client:
        response_a = client.get(f"/api/documents/{doc_a_id}/headers")
        assert response_a.status_code == 200
        cached_a = SimpleHeadersState.get(doc_a_id)
        assert cached_a is not None
        assert cached_a[0] == "hash-a"
        assert cached_a[1] == lines_by_doc[doc_a_id]

        response_a_repeat = client.get(f"/api/documents/{doc_a_id}/headers")
        assert response_a_repeat.status_code == 200

        response_b = client.get(f"/api/documents/{doc_b_id}/headers")
        assert response_b.status_code == 200
        cached_b = SimpleHeadersState.get(doc_b_id)
        assert cached_b is not None
        assert cached_b[0] == "hash-b"
        assert cached_b[1] == lines_by_doc[doc_b_id]

        response_a_third = client.get(f"/api/documents/{doc_a_id}/headers")
        assert response_a_third.status_code == 200

        SimpleHeadersState.clear(doc_a_id)

        response_a_rehydrated = client.get(f"/api/documents/{doc_a_id}/headers")
        assert response_a_rehydrated.status_code == 200
        cached_a_after = SimpleHeadersState.get(doc_a_id)
        assert cached_a_after is not None
        assert cached_a_after[0] == "hash-a"
        assert cached_a_after[1] == lines_by_doc[doc_a_id]

        section_response_a = client.get(
            f"/api/headers/{doc_a_id}/section-text",
            params={"start": 1, "end": 2},
        )
        assert section_response_a.status_code == 200
        assert section_response_a.text == "Doc A Heading\nDoc A Body"

        section_response_b = client.get(
            f"/api/headers/{doc_b_id}/section-text",
            params={"start": 5, "end": 6},
        )
        assert section_response_b.status_code == 200
        assert section_response_b.text == "Doc B Heading\nDoc B Body"

    SimpleHeadersState.clear()
