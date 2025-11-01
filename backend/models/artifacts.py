"""Database models for persisted document artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Column, Enum as SAEnum, Float, LargeBinary, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(UTC)


class DocumentArtifactType(str, Enum):
    """Enumerated artifact families persisted for a document."""

    HEADER_TREE = "header_tree"
    SECTION = "section"
    TABLE_CSV = "table_csv"
    TABLE_JSON = "table_json"
    FIGURE_THUMB = "figure_thumb"
    FIGURE_OCR = "figure_ocr"
    SUMMARY_DOC = "summary_doc"
    SUMMARY_SECTION = "summary_section"
    ENTITIES = "entities"
    EMBEDDINGS_INDEX = "embeddings_index"
    PROMPT_RESPONSE = "prompt_response"
    PAGE_LAYOUT = "page_layout"


class DocumentPage(SQLModel, table=True):
    """Flattened representation of a parsed document page."""

    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_index", name="uq_document_page_index"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    page_index: int = Field(nullable=False)
    width: float = Field(nullable=False)
    height: float = Field(nullable=False)
    is_toc: bool = Field(
        default=False,
        nullable=False,
        description="Flag indicating whether the page was classified as table of contents.",
    )
    text_raw: str = Field(
        default="",
        sa_column=Column(Text, nullable=False),
        description="Concatenated text extracted from the page.",
    )
    layout: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Structured block layout for the page.",
    )
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DocumentTable(SQLModel, table=True):
    """Structured metadata for detected tables within a document."""

    __tablename__ = "document_tables"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    page_index: int = Field(nullable=False)
    bbox: list[float] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Bounding box describing the table location.",
    )
    flavor: str | None = Field(default=None, nullable=True)
    accuracy: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DocumentFigure(SQLModel, table=True):
    """Detected figures, thumbnails, and optional OCR content."""

    __tablename__ = "document_figures"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    page_index: int = Field(nullable=False)
    bbox: list[float] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    thumb_path: str | None = Field(default=None, nullable=True)
    ocr_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DocumentArtifact(SQLModel, table=True):
    """Generic persisted artifact keyed by document and input hash."""

    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "artifact_type",
            "artifact_key",
            "sha_inputs",
            name="uq_document_artifact_cache",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    artifact_type: DocumentArtifactType = Field(
        sa_column=Column(SAEnum(DocumentArtifactType), nullable=False)
    )
    artifact_key: str = Field(nullable=False)
    sha_inputs: str = Field(nullable=False, index=True)
    body: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
        description="Structured payload for the artifact.",
    )
    text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    blob_path: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DocumentEntity(SQLModel, table=True):
    """Named entities identified within a document."""

    __tablename__ = "document_entities"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    entity_type: str = Field(nullable=False, description="Entity category label.")
    value: str = Field(nullable=False)
    span_start: int | None = Field(default=None, nullable=True)
    span_end: int | None = Field(default=None, nullable=True)
    page_index: int | None = Field(default=None, nullable=True)
    section_path: str | None = Field(default=None, nullable=True)
    source: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DocumentEmbedding(SQLModel, table=True):
    """Vector representations associated with document chunks."""

    __tablename__ = "document_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_id",
            "sha_model",
            name="uq_document_embedding_chunk",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    chunk_id: str = Field(nullable=False)
    dimension: int = Field(nullable=False)
    vector: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    norm: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    section_key: str | None = Field(default=None, index=True, nullable=True)
    header_path: str | None = Field(default=None, nullable=True)
    page_index: int | None = Field(default=None, nullable=True)
    sha_model: str = Field(nullable=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class PromptResponse(SQLModel, table=True):
    """LLM prompt / response cache scoped to documents."""

    __tablename__ = "prompt_responses"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "artifact_type",
            "prompt_hash",
            "model",
            name="uq_prompt_response_cache",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True, nullable=False)
    artifact_type: str = Field(nullable=False)
    prompt_hash: str = Field(nullable=False, index=True)
    model: str = Field(nullable=False)
    params: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    request_text_ref: str | None = Field(default=None, nullable=True)
    response_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    usage: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


__all__ = [
    "DocumentArtifact",
    "DocumentArtifactType",
    "DocumentEmbedding",
    "DocumentEntity",
    "DocumentFigure",
    "DocumentPage",
    "DocumentTable",
    "PromptResponse",
]

