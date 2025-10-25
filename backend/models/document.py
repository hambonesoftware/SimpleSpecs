"""Document model definition."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    """Represents an uploaded document tracked by the system."""

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(index=True, description="Original filename of the uploaded document.")
    checksum: str = Field(unique=True, index=True, description="SHA-256 checksum for deduplication.")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp indicating when the file was uploaded.",
    )
    status: str = Field(default="uploaded", description="Processing status for the document.")
