"""FastAPI router exposing the per-section spec extraction workflow."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from backend.config import get_settings

from . import get_engine
from .jobs import enqueue_jobs_for_document, list_job_ids, run_job
from .models import Agent, Document, Section, SpecRecord
from .schemas import SectionWithSpecsOut, SpecExtractionDispatchRequest, SpecRecordOut

router = APIRouter(prefix="/api/specs", tags=["spec-extraction"])


def _session() -> Session:
    return Session(get_engine())


@router.post("/dispatch")
async def dispatch(
    req: SpecExtractionDispatchRequest,
    *,
    background_tasks: BackgroundTasks,
) -> Any:
    document_id = req.documentId
    with _session() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not indexed for specs")
    sections_count, jobs_created = await enqueue_jobs_for_document(document_id)
    if jobs_created:
        for job_id in list_job_ids(document_id, states={"queued"}):
            background_tasks.add_task(run_job, job_id)
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "documentId": document_id,
            "sectionsEnqueued": sections_count,
            "jobsCreated": jobs_created,
        },
    )


@router.get("")
async def list_specs(documentId: str = Query(...)) -> Any:
    document_id = documentId
    with _session() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not indexed for specs")
        sections = session.exec(
            select(Section).where(Section.document_id == document_id)
        ).all()
        settings = get_settings()
        enabled_agents = tuple(settings.specs_enabled_agents) or ("Mechanical",)
        agent_stmt = select(Agent)
        if enabled_agents:
            agent_stmt = agent_stmt.where(Agent.code.in_(enabled_agents))
        agents = session.exec(agent_stmt).all()
        section_ids = [section.id for section in sections]
        records = (
            session.exec(
                select(SpecRecord).where(SpecRecord.section_id.in_(section_ids))
            ).all()
            if section_ids
            else []
        )

    record_map = defaultdict(dict)
    for record in records:
        record_map[record.section_id][record.agent_id] = record

    sections_payload: list[SectionWithSpecsOut] = []
    for section in sections:
        specs: dict[str, SpecRecordOut | None] = {}
        for agent in agents:
            record = record_map.get(section.id, {}).get(agent.id)
            if record is None:
                specs[agent.code] = None
            else:
                specs[agent.code] = SpecRecordOut(
                    agent=agent.code,
                    sectionId=section.id,
                    result=record.result_json,
                    confidence=_format_confidence(record.confidence),
                )
        sections_payload.append(
            SectionWithSpecsOut(
                sectionId=section.id,
                title=section.title,
                pageStart=section.page_start,
                pageEnd=section.page_end,
                status=section.status,
                specs=specs,
            )
        )
    return {
        "ok": True,
        "documentId": document_id,
        "sections": sections_payload,
    }


@router.get("/{section_id:uuid}")
async def get_section_specs(section_id: UUID) -> Any:
    section_key = str(section_id)
    with _session() as session:
        section = session.get(Section, section_key)
        if section is None:
            raise HTTPException(status_code=404, detail="Section not found")
        document = session.get(Document, section.document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not indexed for specs")
        settings = get_settings()
        enabled_agents = tuple(settings.specs_enabled_agents) or ("Mechanical",)
        agent_stmt = select(Agent)
        if enabled_agents:
            agent_stmt = agent_stmt.where(Agent.code.in_(enabled_agents))
        agents = session.exec(agent_stmt).all()
        records = session.exec(
            select(SpecRecord).where(SpecRecord.section_id == section_key)
        ).all()
    record_map = {record.agent_id: record for record in records}
    specs: dict[str, SpecRecordOut | None] = {}
    for agent in agents:
        record = record_map.get(agent.id)
        if record is None:
            specs[agent.code] = None
        else:
            specs[agent.code] = SpecRecordOut(
                agent=agent.code,
                sectionId=section.id,
                result=record.result_json,
                confidence=_format_confidence(record.confidence),
            )
    payload = SectionWithSpecsOut(
        sectionId=section.id,
        title=section.title,
        pageStart=section.page_start,
        pageEnd=section.page_end,
        status=section.status,
        specs=specs,
    )
    return {"ok": True, "section": payload}


@router.get("/status")
async def status(documentId: str = Query(...)) -> Any:
    document_id = documentId
    with _session() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not indexed for specs")
        sections = session.exec(
            select(Section).where(Section.document_id == document_id)
        ).all()
    counts = {"sections": len(sections), "complete": 0, "running": 0, "failed": 0}
    for section in sections:
        if section.status == "complete":
            counts["complete"] += 1
        elif section.status == "failed":
            counts["failed"] += 1
        elif section.status == "running":
            counts["running"] += 1
    return {"ok": True, "counts": counts}


def _format_confidence(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.3f}"
