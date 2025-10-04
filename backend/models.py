"""Pydantic models for the SimpleSpecs backend."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ParsedObject(BaseModel):
    """Normalized representation of a parsed document element."""

    line_id: str = Field(..., description="Unique identifier for the extracted element")
    type: str = Field(..., description="Element type: text, table, image, other")
    page: int | None = Field(None, description="Page number if available")
    bbox: list[float] | None = Field(
        None, description="Bounding box coordinates [x0, y0, x1, y1] where available"
    )
    content: str = Field(..., description="Primary textual content of the element")
    meta: dict[str, Any] | None = Field(
        default=None, description="Additional metadata for the parsed element"
    )


class UploadResponse(BaseModel):
    upload_id: str
    object_count: int


class ObjectsResponse(BaseModel):
    items: list[ParsedObject]
    total: int


class HeadersRequest(BaseModel):
    upload_id: str
    provider: Literal["openrouter", "llamacpp"]
    model: str
    params: dict[str, Any] | None = None
    api_key: str | None = None
    base_url: str | None = None


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
    section_number: str
    section_name: str
    specification: str
    domain: str = "Mechanical"
