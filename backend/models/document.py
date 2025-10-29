"""Document model definition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    """Represents an uploaded document tracked by the system."""

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(
        index=True, description="Original filename of the uploaded document."
    )
    checksum: str = Field(
        unique=True, index=True, description="SHA-256 checksum for deduplication."
    )
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp indicating when the file was uploaded.",
    )
    status: str = Field(
        default="uploaded", description="Processing status for the document."
    )
    mime_type: str | None = Field(
        default=None, description="Detected MIME type for the uploaded document."
    )
    byte_size: int = Field(
        default=0, description="Size of the uploaded document in bytes."
    )
    page_count: int | None = Field(
        default=None, description="Number of pages detected during parsing."
    )
    has_ocr: bool = Field(
        default=False,
        description="Whether OCR was required during the last parse run.",
    )
    used_mineru: bool = Field(
        default=False,
        description="Whether the MinerU fallback parser was used during parsing.",
    )
    parser_version: str | None = Field(
        default=None,
        description="Version identifier for the parser that produced stored artifacts.",
    )
    last_parsed_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent parsing operation.",
    )
