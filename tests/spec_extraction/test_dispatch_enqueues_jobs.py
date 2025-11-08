from __future__ import annotations

from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import persist_sections
from backend.spec_extraction.models import AgentJob, Section


def test_dispatch_enqueues_jobs(client, monkeypatch) -> None:
    """Dispatching should queue five jobs per section without running them."""

    persist_sections(
        document_id="1",
        filename="sample.pdf",
        sections=[
            {
                "header_text": "1 Scope",
                "start_page": 1,
                "end_page": 2,
                "start_global_idx": 0,
                "end_global_idx": 4,
            },
            {
                "header_text": "2 Requirements",
                "start_page": 3,
                "end_page": 5,
                "start_global_idx": 5,
                "end_global_idx": 9,
            },
        ],
    )

    captured: list[str] = []

    async def _noop(job_id: str) -> None:
        captured.append(job_id)

    monkeypatch.setattr("backend.spec_extraction.router.run_job", _noop)

    response = client.post("/api/specs/dispatch", json={"documentId": "1"})
    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "ok": True,
        "documentId": "1",
        "sectionsEnqueued": 2,
        "jobsCreated": 10,
    }

    with Session(get_engine()) as session:
        jobs = session.exec(select(AgentJob)).all()
        assert len(jobs) == 10
        assert {job.state for job in jobs} == {"queued"}
        sections = session.exec(select(Section)).all()
        assert len(sections) == 2
        assert {section.status for section in sections} == {"running"}

    # Background tasks should receive every job identifier once.
    assert len(captured) == 10
