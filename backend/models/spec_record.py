"""Specification approval persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current time in UTC."""

    return datetime.now(UTC)


class SpecRecord(SQLModel, table=True):
    """Frozen specification payload for an analysed document."""

    __tablename__ = "spec_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    state: str = Field(default="draft", index=True, nullable=False)
    reviewer: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
    approved_at: datetime | None = Field(default=None, nullable=True)
    frozen_at: datetime | None = Field(default=None, nullable=True)
    content_hash: str | None = Field(default=None, index=True, nullable=True)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )


class SpecAuditEntry(SQLModel, table=True):
    """Audit trail capturing approvals and export actions."""

    __tablename__ = "spec_audit_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    record_id: int | None = Field(
        default=None, foreign_key="spec_records.id", index=True, nullable=True
    )
    action: str = Field(nullable=False, index=True)
    actor: str | None = Field(default=None, nullable=True)
    summary: str = Field(default="", nullable=False)
    detail: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


__all__ = ["SpecRecord", "SpecAuditEntry"]
