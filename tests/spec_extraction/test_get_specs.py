from __future__ import annotations

from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import persist_sections
from backend.spec_extraction.models import Agent, Section, SpecRecord


def test_get_specs_endpoints(client) -> None:
    """Ensure the retrieval endpoints expose sections and agent payloads."""

    persist_sections(
        document_id="42",
        filename="spec.pdf",
        sections=[
            {
                "header_text": "Safety Requirements",
                "start_page": 10,
                "end_page": 12,
                "start_global_idx": 100,
                "end_global_idx": 120,
            }
        ],
    )

    with Session(get_engine()) as session:
        section = session.exec(select(Section)).one()
        agents = {agent.code: agent for agent in session.exec(select(Agent)).all()}

        record = SpecRecord(
            section_id=section.id,
            agent_id=agents["Mechanical"].id,
            result_json={
                "requirements": [
                    {
                        "text": "Install guard rails.",
                        "level": "MUST",
                        "page_hint": 11,
                    }
                ],
                "notes": ["Verify on site."],
            },
            confidence=0.82,
        )
        session.add(record)
        section.status = "complete"
        session.commit()

        section_id = section.id

    response = client.get("/api/specs", params={"documentId": "42"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["documentId"] == "42"
    assert len(payload["sections"]) == 1
    section_payload = payload["sections"][0]
    assert section_payload["sectionId"] == section_id
    assert section_payload["specs"]["Mechanical"]["result"]["requirements"][0]["text"] == "Install guard rails."
    assert section_payload["specs"]["Mechanical"]["confidence"] == "0.820"
    assert list(section_payload["specs"].keys()) == ["Mechanical"]

    single = client.get(f"/api/specs/{section_id}")
    assert single.status_code == 200
    single_payload = single.json()
    assert single_payload["ok"] is True
    assert single_payload["section"]["sectionId"] == section_id

    status = client.get("/api/specs/status", params={"documentId": "42"})
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload == {
        "ok": True,
        "counts": {"sections": 1, "complete": 1, "running": 0, "failed": 0},
    }
