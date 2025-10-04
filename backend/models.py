"""Pydantic models for the SimpleSpecs backend."""
from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, model_validator


class BoundingBox(BaseModel):
    """Axis-aligned rectangle used for parsed elements."""

    x0: float
    y0: float
    x1: float
    y1: float

    def to_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    @classmethod
    def from_iterable(cls, values: Iterable[float]) -> "BoundingBox":
        x0, y0, x1, y1 = list(values)
        return cls(x0=x0, y0=y0, x1=x1, y1=y1)


class ParsedObject(BaseModel):
    """Normalized representation of a parsed document element."""

    object_id: str = Field(..., description="Unique identifier for the extracted element")
    file_id: str = Field(..., description="Identifier of the parent document")
    kind: str = Field(..., description="Element type such as text, table, or image")
    text: str | None = Field(None, description="Primary textual content of the element")
    content: str | None = Field(
        None,
        description="Alternate textual content retained for backward compatibility",
    )
    page_index: int | None = Field(None, description="Zero-based page index if available")
    bbox: list[float] | None = Field(
        default=None,
        description="Bounding box coordinates [x0, y0, x1, y1] where available",
    )
    order_index: int = Field(..., description="Stable ordering index for reading order")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata for the parsed element"
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_payload(cls, values: Any) -> Any:
        """Normalize legacy payloads emitted by earlier parsing stages."""

        if not isinstance(values, dict):
            return values
        data = dict(values)
        if "object_id" not in data and "line_id" in data:
            data["object_id"] = data.pop("line_id")
        if "file_id" not in data and "document_id" in data:
            data["file_id"] = data.get("document_id")
        if "kind" not in data:
            legacy_type = data.get("type")
            if legacy_type:
                data["kind"] = legacy_type
        if "text" not in data and "content" in data:
            data["text"] = data.get("content")
        if "content" not in data and "text" in data:
            data["content"] = data.get("text")
        if "order_index" not in data:
            if "order" in data:
                data["order_index"] = data["order"]
            else:
                data["order_index"] = 0
        if "page_index" not in data and "page" in data:
            data["page_index"] = data.get("page")
        if "metadata" not in data and "meta" in data:
            data["metadata"] = data.get("meta")
        bbox = data.get("bbox")
        if isinstance(bbox, dict):
            data["bbox"] = [
                bbox.get("x0", 0.0),
                bbox.get("y0", 0.0),
                bbox.get("x1", 0.0),
                bbox.get("y1", 0.0),
            ]
        if "bbox" in data and isinstance(data["bbox"], BoundingBox):
            data["bbox"] = data["bbox"].to_list()
        return data

    @property
    def clean_text(self) -> str:
        """Return the object's textual representation with fallback content."""

        return (self.text or self.content or "").strip()


class SectionSpan(BaseModel):
    """Span metadata linking sections to parsed objects."""

    start_object: str | None = Field(
        None, description="Object identifier marking the first element in the section"
    )
    end_object: str | None = Field(
        None, description="Object identifier marking the last element in the section"
    )
    page_start: int | None = Field(None, description="First page index covered by the section")
    page_end: int | None = Field(None, description="Last page index covered by the section")


class SectionNode(BaseModel):
    """Header tree node."""

    section_id: str
    file_id: str
    number: str | None = None
    title: str
    depth: int
    children: list["SectionNode"] = Field(default_factory=list)
    span: SectionSpan | None = None


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
    spec_id: str
    file_id: str
    section_id: str
    section_number: str | None = None
    section_title: str
    spec_text: str
    confidence: float | None = None
    source_object_ids: list[str] = Field(default_factory=list)


# Resolve recursive definitions for SectionNode
SectionNode.model_rebuild()
