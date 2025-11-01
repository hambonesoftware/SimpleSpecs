"""SQLModel definition for document sections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(UTC)


class DocumentSection(SQLModel, table=True):
    """Canonical section span derived from the simple headers outline."""

    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("document_id", "section_key", name="uq_document_section"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    section_key: str = Field(index=True, nullable=False)
    title: str = Field(nullable=False)
    number: str | None = Field(default=None, nullable=True)
    level: int = Field(default=1, nullable=False)
    start_global_idx: int = Field(nullable=False)
    end_global_idx: int = Field(nullable=False)
    start_page: int | None = Field(default=None, nullable=True)
    end_page: int | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


__all__ = ["DocumentSection"]

