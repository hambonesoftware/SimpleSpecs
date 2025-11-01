"""Tests for the section-gated search endpoint."""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session

from backend.database import get_engine, init_db
from backend.main import app
from backend.models import Document, DocumentSection
from backend.services.simpleheaders_state import SimpleHeadersState


def test_search_endpoint_filters_by_section() -> None:
    """Search results should be restricted to the requested section."""

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        document = Document(filename="sample.pdf", checksum="abc-search")
        session.add(document)
        session.commit()
        session.refresh(document)
        doc_id = int(document.id or 0)
        assert doc_id

        section_a = DocumentSection(
            document_id=doc_id,
            section_key="1-intro::10",
            title="Introduction",
            number="1",
            level=1,
            start_global_idx=10,
            end_global_idx=20,
            start_page=0,
            end_page=0,
        )
        section_b = DocumentSection(
            document_id=doc_id,
            section_key="2-apparatus::30",
            title="Apparatus",
            number="2",
            level=1,
            start_global_idx=30,
            end_global_idx=40,
            start_page=1,
            end_page=1,
        )
        session.add(section_a)
        session.add(section_b)
        session.commit()

    lines = [
        {"global_idx": 10, "text": "Introduction", "page": 0},
        {"global_idx": 12, "text": "Diverter delay is calibrated", "page": 0},
        {"global_idx": 30, "text": "Apparatus", "page": 1},
        {"global_idx": 32, "text": "Time measuring apparatus specifications", "page": 1},
    ]
    SimpleHeadersState.set(doc_id, "hash", lines)

    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get(
                "/api/search",
                params={
                    "doc": doc_id,
                    "q": "diverter delay",
                    "section_key": "1-intro::10",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["matches"], payload
            assert payload["matches"][0]["section_key"] == "1-intro::10"

            routed = client.get(
                "/api/search",
                params={"doc": doc_id, "q": "apparatus"},
            )
            assert routed.status_code == 200
            routed_payload = routed.json()
            assert routed_payload["routed_section_keys"]
            assert any(
                match["section_key"] == "2-apparatus::30"
                for match in routed_payload.get("matches", [])
            )
    finally:
        SimpleHeadersState._store.pop(doc_id, None)  # type: ignore[attr-defined]
        with Session(engine) as cleanup:
            cleanup.exec(
                delete(DocumentSection).where(DocumentSection.document_id == doc_id)
            )
            cleanup.exec(delete(Document).where(Document.id == doc_id))
            cleanup.commit()

