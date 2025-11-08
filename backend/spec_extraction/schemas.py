"""Pydantic schemas used by the spec extraction API."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SpecExtractionDispatchRequest(BaseModel):
    """Request payload for dispatching section extraction jobs."""

    documentId: str = Field(min_length=1, alias="documentId")

    model_config = {
        "populate_by_name": True,
    }


class SpecRecordOut(BaseModel):
    """Serialised view of an agent's extraction output for a section."""

    agent: str
    sectionId: str
    result: Dict[str, Any]
    confidence: Optional[str] = None


class SectionWithSpecsOut(BaseModel):
    """Envelope describing a section and its per-agent outputs."""

    sectionId: str
    title: str
    pageStart: Optional[int] = None
    pageEnd: Optional[int] = None
    status: str
    specs: Dict[str, SpecRecordOut | None]
