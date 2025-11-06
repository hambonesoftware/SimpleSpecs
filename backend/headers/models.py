"""Data models used by the headers extractor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class HeaderItem:
    """Normalised representation of a single header entry."""

    number: Optional[str]
    title: str
    level: int
    page: Optional[int] = None
    order: Optional[int] = None
    source: str = "llm"
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AttemptSummary:
    """Telemetry describing a single ladder attempt."""

    rung: str
    model: str
    status: str
    reason: Optional[str] = None
    chunk_count: int = 0
    retries: int = 0
    duration_s: Optional[float] = None


@dataclass(slots=True)
class ExtractHeadersResult:
    """Result object returned by :func:`extract_headers`."""

    ok: bool
    headers: List[HeaderItem]
    attempts: List[AttemptSummary]
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


__all__ = ["HeaderItem", "AttemptSummary", "ExtractHeadersResult"]
