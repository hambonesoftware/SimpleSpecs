from __future__ import annotations

import asyncio
import types

from sqlmodel import Session

from backend.api import headers as headers_api
from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, init_db, reset_database_state
from backend.models.document import Document
from backend.services.headers import HeaderExtractionResult, HeaderNode
from backend.services.simpleheaders_state import SimpleHeadersState


def test_extract_headers_and_chunks_force_refresh(monkeypatch, tmp_path):
    """The API helper should honour the end-to-end header extraction process."""

    monkeypatch.setenv("HEADERS_MODE", "llm_full")
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
    with Session(engine) as setup_session:
        document = Document(filename="doc.pdf", checksum="abc123")
        setup_session.add(document)
        setup_session.commit()
        setup_session.refresh(document)
        document_id = int(document.id or 0)

    document_dir = settings.upload_dir / str(document_id)
    document_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = document_dir / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF")

    SimpleHeadersState.set(document_id, "stale-hash", [{"global_idx": 999}])

    delete_called: list[int] = []

    def _fake_delete_sections(session, document_id: int) -> None:  # noqa: ANN001
        delete_called.append(document_id)

    monkeypatch.setattr(
        "backend.api.headers.delete_sections_for_document",
        _fake_delete_sections,
    )

    parse_result = object()
    monkeypatch.setattr(
        "backend.api.headers.get_or_create_parse_result",
        lambda **kwargs: (parse_result, False),
    )

    header_outline = [HeaderNode(title="Intro", numbering="1", page=0)]
    header_result = HeaderExtractionResult(
        outline=header_outline,
        fenced_text="#headers#\n#/headers#",
        source="openrouter",
        messages=["outline message"],
    )

    monkeypatch.setattr(
        "backend.api.headers.extract_headers",
        lambda *args, **kwargs: header_result,
    )

    section_stub = types.SimpleNamespace(
        section_key="sec-1",
        title="Intro",
        number="1",
        level=1,
        start_global_idx=0,
        end_global_idx=2,
        start_page=0,
        end_page=0,
    )

    captured: dict[str, object] = {}

    def _fake_build_and_store_sections(
        *,
        session,
        document_id: int,
        simpleheaders,
        lines,
    ):  # noqa: ANN001
        captured["simpleheaders"] = list(simpleheaders)
        captured["lines"] = list(lines)
        return [section_stub]

    monkeypatch.setattr(
        "backend.api.headers.build_and_store_sections",
        _fake_build_and_store_sections,
    )

    class DummyTracer:
        path = "trace.jsonl"
        summary_path = "trace.summary.json"

        def as_list(self):  # noqa: ANN201
            return []

        def log_call(self, *args, **kwargs):  # noqa: ANN201
            return None

        def ev(self, *args, **kwargs):  # noqa: ANN201
            return None

    async def _fake_orchestrator(
        document_bytes: bytes,
        *,
        settings,
        native_headers,
        metadata,
        session,
        document,
        want_trace=False,
        force=False,
    ):  # noqa: ANN001
        captured["force"] = force
        captured["metadata"] = metadata
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
                "llm_raw_responses": ["raw-response"],
                "llm_fenced_blocks": ["block"],
                "lines": [
                    {"text": "Intro", "page": 0, "line_idx": 0, "global_idx": 0},
                    {"text": "Body", "page": 0, "line_idx": 1, "global_idx": 1},
                ],
            },
            DummyTracer(),
        )

    monkeypatch.setattr(
        "backend.api.headers.orchestrate_headers_and_chunks",
        _fake_orchestrator,
    )
    monkeypatch.setattr(
        "backend.routers.headers.extract_headers_and_chunks",
        _fake_orchestrator,
    )

    async def _run() -> dict:
        with Session(engine) as session:
            return await headers_api.extract_headers_and_chunks(
                document_id=document_id,
                settings=settings,
                session=session,
                force=True,
                trace=False,
            )

    response = asyncio.run(_run())

    assert delete_called == [document_id]
    assert captured["force"] is True
    assert captured["metadata"] == {"filename": "doc.pdf", "document_id": document_id}

    cached = SimpleHeadersState.get(document_id)
    assert cached is not None
    cache_hash, cache_lines = cached
    assert cache_hash == "fresh-hash"
    assert len(cache_lines) == 2

    assert response["documentId"] == document_id
    assert response["simpleheaders"][0]["text"] == "Intro"
    assert response["sections"][0]["header_text"] == "Intro"
    assert response.get("docHash") == "fresh-hash"
    assert response["mode"] == "llm_full"
    assert "outline message" in response["messages"]
    assert "orchestrator message" in response["messages"]

