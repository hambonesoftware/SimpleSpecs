"""Models for persisting raw LLM header outlines."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current time in UTC."""

    return datetime.now(UTC)


class HeaderOutlineRun(SQLModel, table=True):
    """Tracks metadata about a single header outline extraction run."""

    __tablename__ = "header_outline_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    model: str = Field(nullable=False)
    prompt_hash: str = Field(index=True, nullable=False)
    source_hash: str = Field(index=True, nullable=False)
    status: str = Field(default="completed", index=True, nullable=False)
    error: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True, nullable=False)


class HeaderOutlineCache(SQLModel, table=True):
    """Stores the raw outline JSON for a given :class:`HeaderOutlineRun`."""

    __tablename__ = "header_outline_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="header_outline_runs.id", index=True, nullable=False)
    document_id: int = Field(index=True, nullable=False)
    outline_json: str = Field(nullable=False)
    meta_json: str | None = Field(default=None, nullable=True)
    tokens_prompt: int | None = Field(default=None, nullable=True)
    tokens_completion: int | None = Field(default=None, nullable=True)
    latency_ms: int | None = Field(default=None, nullable=True)
    unique_key: str | None = Field(default=None, index=True, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True, nullable=False)


__all__ = ["HeaderOutlineRun", "HeaderOutlineCache"]
