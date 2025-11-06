"""Validation helpers for LLM responses."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable

from .models import BucketResult, Level, Requirement
from .normalize import normalize_requirement_text

FENCE_PATTERN = re.compile(r"^```(?P<label>[^\n]+)\n(?P<body>.*)```$", re.DOTALL)


class AbortSignal(Exception):
    """Raised when the LLM explicitly requests to abort the extraction."""


@dataclass
class ValidationError(Exception):
    """Raised when the response payload fails validation."""

    reason: str
    message: str


def strip_code_fence(raw: str) -> str:
    """Return the body of a fenced code block labeled SIMPLEBUCKETS."""

    text = raw.strip()
    if not text:
        raise ValidationError("missing_fence", "response was empty")
    if text == "ABORT":
        raise AbortSignal()
    match = FENCE_PATTERN.match(text)
    if not match:
        lowered = text.lower()
        if text.startswith("["):
            raise ValidationError("bad_label_or_shape", "array payload is not accepted")
        if lowered.startswith("json"):
            raise ValidationError("bad_label_or_shape", "json label without fence is invalid")
        if lowered.startswith("{"):
            raise ValidationError("missing_fence", "payload must be fenced")
        raise ValidationError("missing_fence", "response must be a SIMPLEBUCKETS fence")
    label = match.group("label").strip()
    if label != "SIMPLEBUCKETS":
        raise ValidationError("bad_label_or_shape", "unexpected fence label")
    return match.group("body").strip()


def _ensure_bucket(payload: dict, bucket: str) -> BucketResult:
    value = payload.get(bucket)
    if value is None:
        raise ValidationError("bad_label_or_shape", f"missing bucket '{bucket}'")
    if not isinstance(value, dict):
        raise ValidationError("bad_label_or_shape", f"bucket '{bucket}' must be an object")
    requirements = value.get("requirements", [])
    if requirements is None:
        requirements = []
    if not isinstance(requirements, list):
        raise ValidationError(
            "bad_label_or_shape", f"bucket '{bucket}' requirements must be a list"
        )
    normalized_requirements = []
    for item in requirements:
        if not isinstance(item, dict):
            raise ValidationError("bad_label_or_shape", "requirement entries must be objects")
        text = str(item.get("text", "")).strip()
        level = str(item.get("level", "")).strip().upper()
        page_hint = item.get("page_hint")
        if not text:
            raise ValidationError("bad_label_or_shape", "requirement text missing")
        if level not in {"MUST", "SHOULD", "MAY"}:
            raise ValidationError("bad_label_or_shape", "invalid requirement level")
        if page_hint is not None:
            try:
                page_hint = int(page_hint)
            except (TypeError, ValueError) as exc:
                raise ValidationError("bad_label_or_shape", "page_hint must be int or null") from exc
            if page_hint < 0:
                raise ValidationError("bad_label_or_shape", "page_hint must be >= 0")
        normalized_requirements.append(
            Requirement(
                id="",  # placeholder, filled later during normalization
                text=text,
                level=Level(level),
                page_hint=page_hint,
            )
        )
    return BucketResult(requirements=normalized_requirements)


def validate_schema(raw: str, buckets: Iterable[str]) -> Dict[str, BucketResult]:
    """Parse and validate a SIMPLEBUCKETS payload."""

    body = strip_code_fence(raw)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationError("invalid_json", f"JSON decode error: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("bad_label_or_shape", "payload must be a JSON object")
    normalized: Dict[str, BucketResult] = {}
    for bucket in buckets:
        normalized[bucket] = _ensure_bucket(payload, bucket)
    return normalized


def dedupe_requirements(bucket_results: Dict[str, BucketResult]) -> Dict[str, BucketResult]:
    """Remove duplicate requirement entries by normalized text."""

    for bucket, result in bucket_results.items():
        seen = set()
        unique_requirements = []
        for req in result.requirements:
            signature = normalize_requirement_text(req.text)
            if signature in seen:
                continue
            seen.add(signature)
            unique_requirements.append(req)
        result.requirements = unique_requirements
    return bucket_results
