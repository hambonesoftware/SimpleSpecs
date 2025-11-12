from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, init_db, reset_database_state
from backend.main import app
from backend.models import Document, DocumentSection
from backend.services.headers import HeaderExtractionResult, HeaderNode
from backend.services.outline_cache import latest_outline_for_document, persist_outline_cache
from backend.services.simpleheaders_state import SimpleHeadersState


class DummyTracer:
    path = "trace.jsonl"
    summary_path = "trace.summary.json"

    def as_list(self):  # noqa: D401, ANN201
        return []

    def log_call(self, *args, **kwargs):  # noqa: ANN201
        return None

    def ev(self, *args, **kwargs):  # noqa: ANN201
        return None


def _setup_client(monkeypatch, tmp_path) -> tuple[TestClient, Session, object]:
    db_path = tmp_path / "headers.db"
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

    return TestClient(app), Session(engine), settings


def test_post_headers_persists_outline_and_returns_db_payload(monkeypatch, tmp_path) -> None:
    client, session, settings = _setup_client(monkeypatch, tmp_path)

    document = Document(filename="doc.pdf", checksum="abc123")
    session.add(document)
    session.commit()
    session.refresh(document)
    document_id = int(document.id or 0)

    doc_dir = settings.upload_dir / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    parse_result = object()

    def _fake_parse(**_kwargs):  # noqa: ANN001
        return parse_result, False

    header_outline = [HeaderNode(title="Intro", numbering="1", page=0)]
    header_result = HeaderExtractionResult(
        outline=header_outline,
        fenced_text="#headers#\n#/headers#",
        source="openrouter",
        messages=["outline message"],
    )

    def _fake_build_and_store_sections(*, session, document_id, simpleheaders, lines):  # noqa: ANN001
        section = DocumentSection(
            document_id=document_id,
            section_key="intro",
            title="Intro",
            number="1",
            level=1,
            start_global_idx=0,
            end_global_idx=2,
            start_page=0,
            end_page=0,
        )
        session.add(section)
        session.commit()
        session.refresh(section)
        return [section]

    def _fake_persist_sections(**_kwargs):  # noqa: ANN001 - no-op
        return None

    call_counter: list[str] = []

    async def _fake_orchestrator(
        document_bytes: bytes,
        *,
        session: Session,
        document: Document,
        settings,
        **_kwargs,
    ):  # noqa: ANN001
        call_counter.append("called")
        persist_outline_cache(
            session,
            document_id=int(document.id or 0),
            outline={
                "headers": [{"text": "Intro", "number": "1", "level": 1}],
                "raw_responses": ["raw-response"],
                "fenced_blocks": ["block"],
            },
            meta={"model": settings.headers_llm_model, "doc_hash": "fresh-hash"},
            model=settings.headers_llm_model,
            prompt_hash="prompt-hash",
            source_hash="source-hash",
            supersede_old=True,
        )
        return (
            {
                "headers": [
                    {
                        "text": "Intro",
                        "number": "1",
                        "level": 1,
                        "page": 0,
                        "line_idx": 0,
                        "global_idx": 0,
                    }
                ],
                "sections": [
                    {
                        "header_text": "Intro",
                        "header_number": "1",
                        "level": 1,
                        "start_global_idx": 0,
                        "end_global_idx": 2,
                        "start_page": 0,
                        "end_page": 0,
                    }
                ],
                "mode": "llm_full",
                "messages": ["orchestrator message"],
                "fenced_text": "#headers#\n#/headers#",
                "doc_hash": "fresh-hash",
                "excluded_pages": [],
                "llm_headers": [
                    {"text": "Intro", "number": "1", "level": 1, "page": 0}
                ],
                "lines": [
                    {"text": "Intro", "page": 0, "line_idx": 0, "global_idx": 0},
                    {"text": "Body", "page": 0, "line_idx": 1, "global_idx": 1},
                ],
            },
            DummyTracer(),
        )

    def _fake_get_parse_result(**kwargs):  # noqa: ANN001
        document_obj = kwargs.get("document")
        db_session: Session | None = kwargs.get("session")
        if document_obj is not None and db_session is not None:
            document_obj.last_parsed_at = datetime.now()
            db_session.add(document_obj)
            db_session.commit()
        return _fake_parse(**kwargs)

    monkeypatch.setattr("backend.api.headers.get_or_create_parse_result", _fake_get_parse_result)
    monkeypatch.setattr("backend.api.headers.extract_headers", lambda *args, **kwargs: header_result)
    monkeypatch.setattr("backend.api.headers.build_and_store_sections", _fake_build_and_store_sections)
    monkeypatch.setattr("backend.api.headers.persist_sections", _fake_persist_sections)
    monkeypatch.setattr("backend.api.headers.orchestrate_headers_and_chunks", _fake_orchestrator)
    monkeypatch.setattr(
        "backend.routers.headers.extract_headers_and_chunks",
        _fake_orchestrator,
    )

    response = client.post(f"/api/headers/{document_id}?force=1&trace=0")
    assert response.status_code == 200
    payload = response.json()

    assert payload["documentId"] == document_id
    assert payload["meta"]["promptHash"] == "prompt-hash"
    assert payload["sections"][0]["title"] == "Intro"
    assert payload["sections"][0]["sectionKey"] == "intro"
    assert payload["simpleheaders"][0]["text"] == "Intro"
    assert payload["meta"]["sourceHash"] == "source-hash"
    assert payload["meta"]["model"] == settings.headers_llm_model

    with Session(get_engine()) as verify_session:
        cached = latest_outline_for_document(verify_session, document_id)
        assert cached is not None
        assert payload["runId"] == cached.run_id

    # A subsequent request without ``force`` should reuse DB payload.
    response_cached = client.post(f"/api/headers/{document_id}")
    assert response_cached.status_code == 200
    assert response_cached.json()["runId"] == payload["runId"]
    assert len(call_counter) == 1  # orchestrator called only once

    # GET endpoints should surface the same data.
    get_response = client.get(f"/api/headers/{document_id}")
    assert get_response.status_code == 200
    assert get_response.json()["runId"] == payload["runId"]

    outline_response = client.get(f"/api/headers/{document_id}/outline")
    assert outline_response.status_code == 200
    assert outline_response.json()["runId"] == payload["runId"]

    status_response = client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json() == {"parsed": True, "headers": True}


def test_get_headers_404_when_absent(monkeypatch, tmp_path) -> None:
    client, session, settings = _setup_client(monkeypatch, tmp_path)

    document = Document(filename="doc.pdf", checksum="missing")
    session.add(document)
    session.commit()
    session.refresh(document)
    document_id = int(document.id or 0)

    doc_dir = settings.upload_dir / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF")

    status_response = client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json() == {"parsed": False, "headers": False}

    response = client.get(f"/api/headers/{document_id}")
    assert response.status_code == 404

    outline = client.get(f"/api/headers/{document_id}/outline")
    assert outline.status_code == 404
