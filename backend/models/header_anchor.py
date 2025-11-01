from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(UTC)


class HeaderAnchor(SQLModel, table=True):
    """Resolved anchor for a header located via the vector locator."""

    __tablename__ = "header_anchors"
    __table_args__ = (
        UniqueConstraint("document_id", "header_uid", name="uq_header_anchor_uid"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    header_uid: str = Field(index=True, nullable=False)
    level: int = Field(default=1, nullable=False)
    title: str = Field(nullable=False)
    page: int | None = Field(default=None, nullable=True)
    y_top: float | None = Field(default=None, nullable=True)
    start_line_id: int = Field(nullable=False)
    end_line_id: int = Field(nullable=False)
    lexical: float = Field(default=0.0, nullable=False)
    cosine: float = Field(default=0.0, nullable=False)
    font_rank: float = Field(default=0.0, nullable=False)
    y_bonus: float = Field(default=0.0, nullable=False)
    fused: float = Field(default=0.0, nullable=False)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


__all__ = ["HeaderAnchor"]

