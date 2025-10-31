"""Tests for the section text retrieval endpoint."""

from __future__ import annotations

import pytest
from sqlmodel import Session

pytest.importorskip("rapidfuzz")

from backend.database import get_engine
from backend.models.document import Document
from backend.services.simpleheaders_state import SimpleHeadersState
from backend.main import app


def test_section_text_accepts_reversed_bounds() -> None:
    """The endpoint should gracefully handle ranges where start > end."""

    engine = get_engine()

    with Session(engine) as session:
        document = Document(filename="example.pdf", checksum="checksum")
        session.add(document)
        session.commit()
        session.refresh(document)

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

    assert response.status_code == 200
    assert response.text == "First\nSecond"

