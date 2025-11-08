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


def test_run_job_success() -> None:
    """Successful job execution should persist a spec record and update state."""

    persist_sections(
        document_id="1",
        filename="doc.pdf",
        sections=[
            {
                "header_text": "Mechanical Assembly",
                "start_page": 2,
                "end_page": 3,
                "start_global_idx": 0,
                "end_global_idx": 2,
            }
        ],
    )

    SimpleHeadersState.set(
        1,
        "hash",
        [
            {"global_idx": 0, "text": "The assembly shall support 25 kg loads."},
            {"global_idx": 1, "text": "Provide mounting hardware."},
        ],
    )

    asyncio.run(enqueue_jobs_for_document("1"))

    mock = MockLLMClient(
        responses={
            (
                "Mechanical",
                "primary",
            ): [
                '```SIMPLEBUCKETS\n{"requirements": [{"text": "Provide mounting hardware.", "level": "must", "page_hint": 3}], "notes": []}\n```'
            ]
        }
    )
    set_llm_client(mock)

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
        record = session.exec(
            select(SpecRecord)
            .where(SpecRecord.section_id == section_id)
            .where(SpecRecord.agent_id == agent.id)
        ).one()
        assert record.result_json["requirements"][0]["level"] == "MUST"
        assert record.result_json["requirements"][0]["text"] == "Provide mounting hardware."
        assert record.confidence and record.confidence >= 0.6

        job = session.get(AgentJob, job_id)
        assert job is not None
        assert job.state == "done"
        assert job.error_msg is None

        section = session.get(Section, section_id)
        assert section is not None
        assert section.status == "complete"
