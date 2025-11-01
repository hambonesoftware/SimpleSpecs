"""Tests for the section text retrieval endpoint."""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlmodel import Session

pytest.importorskip("rapidfuzz")

from backend.database import get_engine, init_db
from backend.models.document import Document
from backend.services.simpleheaders_state import SimpleHeadersState
from backend.main import app


def test_section_text_accepts_reversed_bounds() -> None:
    """The endpoint should gracefully handle ranges where start > end."""

    init_db()
    engine = get_engine()

    with Session(engine) as session:
        session.exec(delete(Document).where(Document.checksum == "checksum-section"))
        session.commit()
        document = Document(filename="example.pdf", checksum="checksum-section")
        session.add(document)
        session.commit()
        session.refresh(document)
        doc_id = int(document.id or 0)

    lines = [
        {"global_idx": 36, "text": "First"},
        {"global_idx": 664, "text": "Second"},
    ]
    SimpleHeadersState.set(document.id, "hash", lines)

    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get(
                f"/api/headers/{document.id}/section-text",
                params={"start": 664, "end": 36},
            )
    finally:
        SimpleHeadersState._store.pop(document.id, None)  # type: ignore[attr-defined]
        with Session(engine) as cleanup:
            if doc_id:
                cleanup.exec(delete(Document).where(Document.id == doc_id))
                cleanup.commit()

    assert response.status_code == 200
    assert response.text == "First\nSecond"

