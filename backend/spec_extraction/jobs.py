"""Background job orchestration for per-section spec extraction."""

from __future__ import annotations

import json
import logging
from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, Iterator, Sequence

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.config import get_settings
from backend.services.simpleheaders_state import SimpleHeadersState

from . import get_engine, init_db
from .llm_client import ExtractionResult, LLMClient
from .models import Agent, AgentJob, Document, Header, Section, SpecRecord

init_db()

_LLM_CLIENT: LLMClient | None = None

LOGGER = logging.getLogger(__name__)


def set_llm_client(client: LLMClient) -> None:
    """Override the default LLM client (useful for tests)."""

    global _LLM_CLIENT
    _LLM_CLIENT = client


def get_llm_client() -> LLMClient:
    """Return the configured LLM client, creating it if necessary."""

    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        _LLM_CLIENT = LLMClient()
    return _LLM_CLIENT


@contextmanager
def _session_scope() -> Iterator[Session]:
    session = Session(get_engine())
    try:
        yield session
    finally:
        session.close()


@dataclass
class _SectionSnapshot:
    id: str
    document_id: str
    title: str
    page_start: int | None
    page_end: int | None
    start_global_idx: int | None
    end_global_idx: int | None


@dataclass
class _AgentSnapshot:
    id: int
    code: str


def _section_sort_key(section: Section) -> tuple:
    """Return a deterministic ordering key for sections."""

    return (
        section.start_global_idx is None,
        section.start_global_idx or 0,
        section.page_start is None,
        section.page_start or 0,
        section.created_at,
        section.id,
    )


async def enqueue_jobs_for_document(document_id: str) -> tuple[int, int]:
    """Create queued jobs for every section/agent combination."""

    settings = get_settings()
    enabled_agents = tuple(settings.specs_enabled_agents) or ("Mechanical",)
    max_headers = settings.specs_max_headers

    with _session_scope() as session:
        document = session.get(Document, document_id)
        if document is None:
            return 0, 0
        sections = session.exec(
            select(Section).where(Section.document_id == document_id)
        ).all()
        if not sections:
            return 0, 0

        sections = sorted(sections, key=_section_sort_key)
        if max_headers and max_headers > 0:
            sections = sections[:max_headers]

        agent_query = select(Agent)
        if enabled_agents:
            agent_query = agent_query.where(Agent.code.in_(enabled_agents))
        agents = session.exec(agent_query).all()
        if not agents:
            return len(sections), 0

        sections_count = len(sections)
        jobs_created = 0
        now = datetime.now(UTC)
        for section in sections:
            section.status = "running"
            section.updated_at = now
            for agent in agents:
                existing = session.exec(
                    select(AgentJob).where(
                        AgentJob.section_id == section.id,
                        AgentJob.agent_id == agent.id,
                    )
                ).first()
                if existing is None:
                    job = AgentJob(section_id=section.id, agent_id=agent.id)
                    session.add(job)
                    jobs_created += 1
                elif existing.state not in {"done", "running"}:
                    existing.state = "queued"
                    existing.error_msg = None
        session.commit()
        return sections_count, jobs_created


async def run_job(job_id: str) -> None:
    """Execute a single agent job safely."""

    client = get_llm_client()
    with _session_scope() as session:
        job = session.get(AgentJob, job_id)
        if job is None or job.state == "done":
            return

        section = session.get(Section, job.section_id)
        agent = session.get(Agent, job.agent_id)
        if section is None or agent is None:
            job.state = "error"
            job.error_msg = "Missing section or agent"
            session.commit()
            return

        section_snapshot = _SectionSnapshot(
            id=section.id,
            document_id=section.document_id,
            title=section.title,
            page_start=section.page_start,
            page_end=section.page_end,
            start_global_idx=section.start_global_idx,
            end_global_idx=section.end_global_idx,
        )
        agent_snapshot = _AgentSnapshot(id=agent.id, code=agent.code)

        job.state = "running"
        job.attempt += 1
        session.commit()

    section_text = _render_section_text(section_snapshot)
    if not section_text:
        _record_job_error(job_id, "Section text unavailable")
        return

    LOGGER.info(
        "[specs] dispatching LLM request document=%s section=%s agent=%s pages=%s-%s",
        section_snapshot.document_id,
        section_snapshot.title,
        agent_snapshot.code,
        section_snapshot.page_start,
        section_snapshot.page_end,
    )

    payload = json.dumps(
        {
            "title": section_snapshot.title,
            "text": section_text,
            "page_start": section_snapshot.page_start,
            "page_end": section_snapshot.page_end,
        }
    )

    try:
        result: ExtractionResult = await client.extract_specs(
            payload,
            agent_code=agent_snapshot.code,
            timeout_s=None,
        )
    except Exception as exc:  # pragma: no cover - defensive
        _record_job_error(job_id, str(exc))
        return

    with _session_scope() as session:
        job = session.get(AgentJob, job_id)
        if job is None:
            return
        section = session.get(Section, job.section_id)
        agent = session.get(Agent, job.agent_id)
        if section is None or agent is None:
            job.state = "error"
            job.error_msg = "Missing section or agent"
            job.finished_at = datetime.now(UTC)
            session.commit()
            return

        _upsert_spec_record(session, section, agent, result)
        job.state = "done"
        job.error_msg = None
        job.finished_at = datetime.now(UTC)
        _update_section_status(session, section)
        session.commit()


def _record_job_error(job_id: str, message: str) -> None:
    with _session_scope() as session:
        job = session.get(AgentJob, job_id)
        if job is None:
            return
        job.state = "error"
        job.error_msg = message
        job.finished_at = datetime.now(UTC)
        section = session.get(Section, job.section_id)
        if section is not None:
            _update_section_status(session, section)
        session.commit()


def _upsert_spec_record(
    session: Session,
    section: Section,
    agent: Agent,
    result: ExtractionResult,
) -> None:
    """Persist or update the spec record for ``section``/``agent``."""

    record = session.exec(
        select(SpecRecord).where(
            SpecRecord.section_id == section.id,
            SpecRecord.agent_id == agent.id,
        )
    ).first()
    if record is None:
        record = SpecRecord(
            section_id=section.id,
            agent_id=agent.id,
            result_json=result.payload,
            confidence=result.confidence,
        )
        session.add(record)
    else:
        record.result_json = result.payload
        record.confidence = result.confidence
        record.updated_at = datetime.now(UTC)


def _update_section_status(session: Session, section: Section) -> None:
    """Recompute the aggregate status for ``section`` based on job states."""

    jobs = session.exec(
        select(AgentJob).where(AgentJob.section_id == section.id)
    ).all()
    if not jobs:
        section.status = "pending"
    else:
        states = {job.state for job in jobs}
        if "error" in states:
            section.status = "failed"
        elif states.issubset({"done"}):
            section.status = "complete"
        elif states & {"running", "queued", "retry"}:
            section.status = "running"
        else:
            section.status = "pending"
    section.updated_at = datetime.now(UTC)


def _render_section_text(section: _SectionSnapshot) -> str:
    """Return the raw text slice for the section using cached header lines."""

    try:
        doc_id = int(section.document_id)
    except (TypeError, ValueError):
        return ""
    cached = SimpleHeadersState.get(doc_id)
    if cached is None:
        return ""
    _, lines = cached
    if not lines:
        return ""
    start = section.start_global_idx or 0
    end = section.end_global_idx or start
    text_lines: list[str] = []
    for line in lines:
        try:
            idx = int(line.get("global_idx", -1))
        except (TypeError, ValueError):
            continue
        if start <= idx <= end:
            text = str(line.get("text", "")).rstrip()
            if text:
                text_lines.append(text)
    return "\n".join(text_lines).strip()


def persist_sections(
    *,
    document_id: str,
    filename: str,
    sections: Sequence[dict],
    headers: Sequence[dict] | None = None,
) -> None:
    """Persist section metadata emitted by the alignment pipeline."""

    timestamp = datetime.now(UTC)
    with _session_scope() as session:
        document = session.get(Document, document_id)
        if document is None:
            document = Document(id=document_id, filename=filename, created_at=timestamp)
            session.add(document)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                document = session.get(Document, document_id)

        sections_by_start: dict[int, str] = {}
        for entry in sections:
            title = str(entry.get("header_text") or entry.get("title") or "").strip()
            if not title:
                continue
            page_start = _safe_int(entry.get("start_page"))
            page_end = _safe_int(entry.get("end_page"))
            start_idx = _safe_int(entry.get("start_global_idx"))
            end_idx = _safe_int(entry.get("end_global_idx"))
            existing = session.exec(
                select(Section).where(
                    Section.document_id == document_id,
                    Section.title == title,
                    Section.page_start == page_start,
                    Section.page_end == page_end,
                )
            ).first()
            if existing is None:
                section = Section(
                    document_id=document_id,
                    title=title,
                    page_start=page_start,
                    page_end=page_end,
                    start_global_idx=start_idx,
                    end_global_idx=end_idx,
                    status="pending",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(section)
                session.flush()
            else:
                section = existing
                updated = False
                if existing.start_global_idx != start_idx:
                    existing.start_global_idx = start_idx
                    updated = True
                if existing.end_global_idx != end_idx:
                    existing.end_global_idx = end_idx
                    updated = True
                if updated:
                    existing.updated_at = timestamp

            if start_idx is not None and section.id:
                sections_by_start[start_idx] = section.id

        if headers is not None:
            _persist_headers(
                session,
                document_id=document_id,
                headers=headers,
                sections_by_start=sections_by_start,
            )

        session.commit()


def _persist_headers(
    session: Session,
    *,
    document_id: str,
    headers: Sequence[dict],
    sections_by_start: dict[int, str],
) -> None:
    """Replace persisted headers for ``document_id`` with the supplied payload."""

    session.exec(delete(Header).where(Header.document_id == document_id))

    if not headers:
        return

    sorted_starts = sorted((idx, section_id) for idx, section_id in sections_by_start.items())
    start_values = [item[0] for item in sorted_starts]
    section_ids = [item[1] for item in sorted_starts]

    for entry in headers:
        title = str(entry.get("text") or entry.get("title") or "").strip()
        if not title:
            continue
        number_raw = entry.get("number")
        number = str(number_raw).strip() if number_raw not in (None, "") else None
        level = _safe_int(entry.get("level")) or 1
        page = _safe_int(entry.get("page"))
        line_idx = _safe_int(entry.get("line_idx"))
        global_idx = _safe_int(entry.get("global_idx"))

        section_id: str | None = None
        if global_idx is not None and start_values:
            position = bisect_right(start_values, global_idx) - 1
            if position >= 0:
                section_id = section_ids[position]

        header = Header(
            document_id=document_id,
            section_id=section_id,
            title=title,
            number=number,
            level=level,
            page=page,
            line_idx=line_idx,
            global_idx=global_idx,
        )
        session.add(header)


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_job_ids(document_id: str, *, states: Iterable[str] | None = None) -> list[str]:
    """Return job identifiers for ``document_id`` filtered by ``states`` if provided."""

    with _session_scope() as session:
        statement = select(AgentJob.id).join(Section, Section.id == AgentJob.section_id).where(
            Section.document_id == document_id
        )
        if states:
            statement = statement.where(AgentJob.state.in_(set(states)))
        return [row[0] for row in session.exec(statement)]
