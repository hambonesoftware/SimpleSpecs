"""SQLModel table definitions for the per-section spec extraction workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Document(SQLModel, table=True):
    """Tracked document eligible for per-section extraction."""

    __tablename__ = "specx_documents"

    id: str = Field(primary_key=True)
    filename: str = Field(nullable=False)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class Section(SQLModel, table=True):
    """Aligned section segment persisted for downstream extraction."""

    __tablename__ = "specx_sections"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "title",
            "page_start",
            "page_end",
            name="uq_spec_section_span",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    document_id: str = Field(foreign_key="specx_documents.id", index=True, nullable=False)
    title: str = Field(nullable=False)
    page_start: Optional[int] = Field(default=None)
    page_end: Optional[int] = Field(default=None)
    start_global_idx: Optional[int] = Field(default=None, index=True)
    end_global_idx: Optional[int] = Field(default=None)
    status: str = Field(default="pending", nullable=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class Header(SQLModel, table=True):
    """LLM-aligned header metadata persisted for downstream extraction."""

    __tablename__ = "specx_headers"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "title",
            "page",
            "line_idx",
            name="uq_spec_header_span",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    document_id: str = Field(foreign_key="specx_documents.id", index=True, nullable=False)
    section_id: Optional[str] = Field(
        default=None,
        foreign_key="specx_sections.id",
        nullable=True,
        index=True,
    )
    title: str = Field(nullable=False)
    number: Optional[str] = Field(default=None, nullable=True)
    level: int = Field(default=1, nullable=False)
    page: Optional[int] = Field(default=None, nullable=True)
    line_idx: Optional[int] = Field(default=None, nullable=True)
    global_idx: Optional[int] = Field(default=None, nullable=True, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class Agent(SQLModel, table=True):
    """Static lookup table describing the configured agents."""

    __tablename__ = "specx_agents"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True, nullable=False)
    description: str = Field(default="", nullable=False)


class AgentJob(SQLModel, table=True):
    """Work item representing a pending extraction attempt for a section/agent pair."""

    __tablename__ = "specx_agent_jobs"
    __table_args__ = (
        UniqueConstraint("section_id", "agent_id", name="uq_spec_agent_job"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    section_id: str = Field(foreign_key="specx_sections.id", index=True, nullable=False)
    agent_id: int = Field(foreign_key="specx_agents.id", index=True, nullable=False)
    state: str = Field(default="queued", nullable=False, index=True)
    attempt: int = Field(default=0, nullable=False)
    queued_at: datetime = Field(default_factory=_utcnow, nullable=False)
    finished_at: datetime | None = Field(default=None)
    error_msg: str | None = Field(default=None)


class SpecRecord(SQLModel, table=True):
    """Persistent extraction result for a section/agent pair."""

    __tablename__ = "specx_records"
    __table_args__ = (
        UniqueConstraint("section_id", "agent_id", name="uq_spec_record"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    section_id: str = Field(foreign_key="specx_sections.id", index=True, nullable=False)
    agent_id: int = Field(foreign_key="specx_agents.id", index=True, nullable=False)
    result_json: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    confidence: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": _utcnow},
    )


__all__ = [
    "Agent",
    "AgentJob",
    "Header",
    "Document",
    "Section",
    "SpecRecord",
]
