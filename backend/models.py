"""Pydantic models for the SimpleSpecs backend."""
from __future__ import annotations

from typing import Annotated, Any, Dict, Iterable, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
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


class Word(BaseModel):
    text: str
    bbox: Optional[BoundingBox] = None
    font: Optional[str] = None
    size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    color: Optional[str] = None
    page_index: Optional[int] = None
    line_index: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class _ObjectBase(BaseModel):
    """Canonical fields for any parsed object."""

    model_config = ConfigDict(extra="ignore")

    object_id: str = Field(..., description="Unique id for the extracted element")
    file_id: str = Field(..., description="Owning file/upload id")
    kind: str

    text: Optional[str] = None
    page_index: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    order_index: int = Field(0, ge=0, description="Reading-order index")
    tokens: Optional[int] = None
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("bbox", mode="before")
    @classmethod
    def _coerce_bbox(cls, value: Any) -> Any:
        if value is None or isinstance(value, BoundingBox):
            return value
        return BoundingBox.model_validate(value)

    @field_validator("children_ids", mode="before")
    @classmethod
    def _ensure_children_ids(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        raise TypeError("children_ids must be a sequence of identifiers")

    @field_validator("metadata", mode="before")
    @classmethod
    def _ensure_metadata(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise TypeError("metadata must be a mapping")

    @field_serializer("bbox")
    def _serialize_bbox(self, value: BoundingBox | None) -> list[float] | None:
        if value is None:
            return None
        return value.to_list()


class LineObject(_ObjectBase):
    kind: Literal["line"] = "line"
    words: List[Word] = Field(default_factory=list)
    is_blank: Optional[bool] = None
    line_index: Optional[int] = None


class ParagraphObject(_ObjectBase):
    kind: Literal["para"] = "para"
    line_span: Optional[List[int]] = None
    paragraph_index: Optional[int] = None


class HeaderObject(_ObjectBase):
    kind: Literal["header"] = "header"
    level: int
    number: Optional[str] = None
    normalized_text: Optional[str] = None
    path: Optional[str] = None


class TableObject(_ObjectBase):
    kind: Literal["table"] = "table"
    n_rows: Optional[int] = None
    n_cols: Optional[int] = None
    has_header_row: Optional[bool] = None
    markdown: Optional[str] = None


class FigureObject(_ObjectBase):
    kind: Literal["figure"] = "figure"
    caption: Optional[str] = None
    ref_id: Optional[str] = None


ParsedObject = Annotated[
    Union[LineObject, ParagraphObject, HeaderObject, TableObject, FigureObject],
    Field(discriminator="kind"),
]


PARSED_OBJECT_ADAPTER = TypeAdapter(ParsedObject)
PARSED_OBJECT_TYPES = (LineObject, ParagraphObject, HeaderObject, TableObject, FigureObject)

LINE_KIND = "line"
PARAGRAPH_KIND = "para"
HEADER_KIND = "header"
TABLE_KIND = "table"
FIGURE_KIND = "figure"


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
    page_number: int | None = None
    line_number: int | None = None
    chunk_text: str | None = None


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
