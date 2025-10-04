"""Pydantic models for the SimpleSpecs backend."""
from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class BoundingBox(BaseModel):
    """Axis-aligned bounding box expressed as ``(x0, y0, x1, y1)``."""

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, dict):
            if {"x0", "y0", "x1", "y1"}.issubset(value.keys()):
                return value
        if isinstance(value, Iterable):
            items = list(value)
            if len(items) == 4:
                return {
                    "x0": float(items[0]),
                    "y0": float(items[1]),
                    "x1": float(items[2]),
                    "y1": float(items[3]),
                }
        raise TypeError("BoundingBox requires four coordinates")

    def to_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class SectionSpan(BaseModel):
    """Half-open span referencing parsed object identifiers."""

    start_object: str | None = None
    end_object: str | None = None


class SectionNode(BaseModel):
    """Hierarchical section description returned by header discovery."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    section_id: str
    file_id: str
    title: str
    depth: int
    number: str | None = None
    span: SectionSpan | None = None
    children: list["SectionNode"] = Field(default_factory=list)

    @field_validator("children", mode="before")
    @classmethod
    def _ensure_children(cls, value: Any) -> Any:
        if value is None:
            return []
        return value


class ParsedObject(BaseModel):
    """Normalized representation of a parsed document element."""

    model_config = ConfigDict(extra="allow")

    object_id: str = Field(..., description="Unique identifier for the extracted element")
    file_id: str = Field(..., description="Identifier of the owning file")
    kind: str = Field(..., description="Element type: text, table, image, other")
    text: str | None = Field(None, description="Primary textual content of the element")
    page_index: int | None = Field(None, description="Zero-based page index if available")
    bbox: BoundingBox | None = Field(
        None, description="Bounding box coordinates [x0, y0, x1, y1] where available"
    )
    order_index: int = Field(0, description="Document order index assigned during ingestion")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata for the parsed element"
    )

    @field_validator("bbox", mode="before")
    @classmethod
    def _coerce_bbox(cls, value: Any) -> Any:
        if value is None or isinstance(value, BoundingBox):
            return value
        return BoundingBox.model_validate(value)

    @field_validator("order_index")
    @classmethod
    def _non_negative_order(cls, value: int) -> int:
        if value < 0:
            raise ValueError("order_index must be non-negative")
        return value

    @field_serializer("bbox")
    def _serialize_bbox(self, value: BoundingBox | None) -> list[float] | None:
        if value is None:
            return None
        return value.to_list()


class UploadResponse(BaseModel):
    upload_id: str
    object_count: int


class ObjectsResponse(BaseModel):
    items: list[ParsedObject]
    total: int


class OpenRouterHeadersRequest(BaseModel):
    upload_id: str
    model: str
    params: dict[str, Any] | None = None
    api_key: str
    base_url: str | None = None


class OllamaHeadersRequest(BaseModel):
    upload_id: str
    model: str
    params: dict[str, Any] | None = None
    base_url: str


class HeaderItem(BaseModel):
    section_number: str
    section_name: str


class SpecsRequest(BaseModel):
    upload_id: str
    provider: Literal["openrouter", "llamacpp"]
    model: str
    params: dict[str, Any] | None = None
    api_key: str | None = None
    base_url: str | None = None


class SpecItem(BaseModel):
    """LLM extracted mechanical specification tied to a section."""

    spec_id: str
    file_id: str
    section_id: str
    section_title: str
    spec_text: str
    source_object_ids: list[str] = Field(default_factory=list)
    section_number: str | None = None
    confidence: float | None = None

    @field_validator("source_object_ids", mode="before")
    @classmethod
    def _coerce_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        raise TypeError("source_object_ids must be a sequence")
