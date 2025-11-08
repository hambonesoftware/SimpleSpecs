"""Pydantic models used by the spec-search pipeline."""
from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, Field, RootModel, field_validator

BucketName = Literal["mechanical", "electrical", "software", "controls"]


class Level(str, Enum):
    """Requirement criticality level enforced in the contract."""

    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"


class Requirement(BaseModel):
    """Normalized requirement element returned to clients."""

    id: str
    text: str
    level: Level
    page_hint: Optional[int] = Field(default=None, ge=0)

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class BucketResult(BaseModel):
    """Container for requirements belonging to a bucket."""

    requirements: List[Requirement] = Field(default_factory=list)


class AttemptReason(str, Enum):
    """Machine readable reasons attached to each rung attempt."""

    OK = "ok"
    MISSING_FENCE = "missing_fence"
    BAD_LABEL = "bad_label"
    INVALID_JSON = "invalid_json"
    ABORT_TOKEN = "abort_token"
    TIMEOUT = "timeout"
    EMPTY = "empty"
    OTHER = "other"


class AttemptTelemetry(BaseModel):
    """Metadata collected per attempt on the retry ladder."""

    rung: Literal["try-1", "try-2", "chunked", "fallback-model", "legacy"]
    model: str
    input_tokens_est: int
    response_bytes: int
    parsed: bool
    reason: AttemptReason


class SpecSearchMeta(BaseModel):
    """Meta block included with every response."""

    attempts: List[AttemptTelemetry] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    log_path: Optional[str] = None


class SpecSearchData(RootModel):
    __annotations__ = {"root": Dict[str, BucketResult]}
    """Dynamic mapping of buckets to requirement results."""

    @classmethod
    def empty(cls, bucket_names: Iterable[str]) -> "SpecSearchData":
        return cls({name: BucketResult() for name in bucket_names})

    @property
    def buckets(self) -> Dict[str, BucketResult]:
        return self.root


class SpecSearchResponse(BaseModel):
    """Stable response envelope returned by the API."""

    ok: bool
    data: Optional[SpecSearchData] = None
    error: Optional[str] = None
    meta: SpecSearchMeta = Field(default_factory=SpecSearchMeta)


class SpecSearchRequest(BaseModel):
    """Incoming request payload for a spec-search run."""

    document_id: Optional[str] = None
    text: str
    buckets: List[str] = Field(
        default_factory=lambda: ["mechanical", "electrical", "software", "controls"]
    )

    @field_validator("buckets", mode="before")
    @classmethod
    def _normalize_bucket(cls, value: Iterable[str]) -> List[str]:
        if value is None:
            value = ["mechanical", "electrical", "software", "controls"]
        if isinstance(value, str):
            value = [value]
        normalized: List[str] = []
        for bucket in value:
            bucket_value = str(bucket).strip().lower()
            if not bucket_value:
                raise ValueError("bucket names must be non-empty strings")
            normalized.append(bucket_value)
        return normalized

    @field_validator("text")
    @classmethod
    def _text_minimum(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text must be provided")
        return value
