from __future__ import annotations

from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import persist_sections
from backend.spec_extraction.models import AgentJob, Section


def test_dispatch_enqueues_jobs(client, monkeypatch) -> None:
    """Dispatching should queue one Mechanical job per section without running it."""

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
        "jobsCreated": 2,
    }

    with Session(get_engine()) as session:
        jobs = session.exec(select(AgentJob)).all()
        assert len(jobs) == 2
        assert {job.state for job in jobs} == {"queued"}
        sections = session.exec(select(Section)).all()
        assert len(sections) == 2
        assert {section.status for section in sections} == {"running"}

    # Background tasks should receive every job identifier once.
    assert len(captured) == 2


def test_dispatch_respects_header_limit(client, monkeypatch) -> None:
    """Only the first configured number of sections should be enqueued."""

    sections = []
    for idx in range(12):
        sections.append(
            {
                "header_text": f"Section {idx+1}",
                "start_page": idx + 1,
                "end_page": idx + 1,
                "start_global_idx": idx * 5,
                "end_global_idx": idx * 5 + 4,
            }
        )

    persist_sections(document_id="9", filename="limit.pdf", sections=sections)

    captured: list[str] = []

    async def _noop(job_id: str) -> None:
        captured.append(job_id)

    monkeypatch.setattr("backend.spec_extraction.router.run_job", _noop)

    response = client.post("/api/specs/dispatch", json={"documentId": "9"})
    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "ok": True,
        "documentId": "9",
        "sectionsEnqueued": 10,
        "jobsCreated": 10,
    }

    with Session(get_engine()) as session:
        all_sections = session.exec(select(Section).where(Section.document_id == "9")).all()
        running = [section for section in all_sections if section.status == "running"]
        pending = [section for section in all_sections if section.status == "pending"]
        assert len(running) == 10
        assert len(pending) == 2
        jobs = session.exec(
            select(AgentJob).where(AgentJob.section_id.in_([section.id for section in all_sections]))
        ).all()
        assert len(jobs) == 10

    assert len(captured) == 10
