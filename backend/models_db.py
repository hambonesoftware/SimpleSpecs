"""Database models for SimpleSpecs."""
from __future__ import annotations

from datetime import datetime, timezone
from sqlmodel import Field, SQLModel

from backend.constants import MAX_TOKENS_LIMIT


class ModelSettingsBase(SQLModel):
    """Shared fields for model settings records."""

    provider: str = Field(default="openrouter", max_length=50)
    model: str = Field(default="", max_length=255)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=MAX_TOKENS_LIMIT, ge=16, le=32768)
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelSettings(ModelSettingsBase, table=True):
    """Persisted model configuration for LLM interactions."""

    id: int | None = Field(default=None, primary_key=True)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class ModelSettingsRead(ModelSettingsBase):
    """Response model for returning persisted settings."""

    updated_at: datetime


class ModelSettingsUpdate(ModelSettingsBase):
    """Request model for updating persisted settings."""

    pass
