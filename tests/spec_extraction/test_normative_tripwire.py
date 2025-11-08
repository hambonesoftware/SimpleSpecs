from __future__ import annotations

import asyncio
from typing import Mapping, Sequence

from sqlmodel import Session, select

from backend.spec_extraction import get_engine
from backend.spec_extraction.jobs import (
    enqueue_jobs_for_document,
    persist_sections,
    run_job,
    set_llm_client,
)
from backend.spec_extraction.llm_client import LLMClient
from backend.spec_extraction.models import Agent, AgentJob, Section, SpecRecord
from backend.services.simpleheaders_state import SimpleHeadersState


class _StubService:
    def generate(self, **kwargs):  # pragma: no cover - should never be invoked
        raise AssertionError("generate should not be called in tests")


class _TripwireClient(LLMClient):
    def __init__(self) -> None:
        super().__init__(
            primary_model="primary-model",
            fallback_model="fallback-model",
            timeout_s=5,
            retry_max=0,
            llm_service=_StubService(),
        )
        self.calls: list[str] = []

    async def _call_model(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model: str,
        timeout: int,
    ) -> str:
        self.calls.append(model)
        if model == "primary-model":
            return '```SIMPLEBUCKETS\n{"requirements": [], "notes": []}\n```'
        if model == "fallback-model":
            return (
                '```SIMPLEBUCKETS\n{"requirements": '
                '[{"text": "System shall provide backup power.", "level": "should", "page_hint": 7}], '
                '"notes": []}\n```'
            )
        raise AssertionError(f"Unexpected model {model}")


def test_normative_tripwire_triggers_fallback() -> None:
    """Normative text with empty primary output should invoke fallback model."""

    persist_sections(
        document_id="1",
        filename="doc.pdf",
        sections=[
            {
                "header_text": "Mechanical",
                "start_page": 6,
                "end_page": 7,
                "start_global_idx": 20,
                "end_global_idx": 22,
            }
        ],
    )

    SimpleHeadersState.set(
        1,
        "hash",
        [
            {"global_idx": 20, "text": "The assembly shall resist 5 g vibration."},
            {"global_idx": 21, "text": "Fasteners must be torqued to 45 N·m."},
        ],
    )

    asyncio.run(enqueue_jobs_for_document("1"))

    client = _TripwireClient()
    set_llm_client(client)

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
        assert record.result_json["requirements"]
        assert record.result_json["requirements"][0]["level"] == "SHOULD"

    assert client.calls == ["primary-model", "fallback-model"]
