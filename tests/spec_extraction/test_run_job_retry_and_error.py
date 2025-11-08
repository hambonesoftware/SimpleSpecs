from __future__ import annotations

import asyncio

from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import (
    enqueue_jobs_for_document,
    persist_sections,
    run_job,
    set_llm_client,
)
from backend.spec_extraction.llm_client import MockLLMClient
from backend.spec_extraction.models import Agent, AgentJob, Section, SpecRecord
from backend.services.simpleheaders_state import SimpleHeadersState


def test_run_job_retry_and_error() -> None:
    """Failed retries should mark the job and section appropriately."""

    persist_sections(
        document_id="1",
        filename="doc.pdf",
        sections=[
            {
                "header_text": "Mechanical",
                "start_page": 4,
                "end_page": 5,
                "start_global_idx": 10,
                "end_global_idx": 12,
            }
        ],
    )

    SimpleHeadersState.set(
        1,
        "hash",
        [
            {"global_idx": 10, "text": "Support frame should provide redundancy."},
            {"global_idx": 11, "text": "Add guard rail."},
        ],
    )

    asyncio.run(enqueue_jobs_for_document("1"))

    failing = MockLLMClient(
        responses={
            ("Mechanical", "primary"): ["missing fence", "ABORT"],
        }
    )
    set_llm_client(failing)

    with Session(get_engine()) as session:
        section = session.exec(select(Section)).one()
        agent = session.exec(select(Agent).where(Agent.code == "Mechanical")).one()
        job = session.exec(
            select(AgentJob)
            .where(AgentJob.section_id == section.id)
            .where(AgentJob.agent_id == agent.id)
        ).one()
        job_id = job.id
        section_id = section.id

    asyncio.run(run_job(job_id))

    with Session(get_engine()) as session:
        job = session.get(AgentJob, job_id)
        assert job is not None
        assert job.state == "error"
        assert "ABORT" in (job.error_msg or "")

        record = session.exec(select(SpecRecord)).all()
        assert record == []

        section = session.get(Section, section_id)
        assert section is not None
        assert section.status == "failed"
