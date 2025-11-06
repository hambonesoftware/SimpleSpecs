"""Normalization helpers for spec search outputs."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .models import Level

WORD_BOUNDARY = re.compile(r"\s+")
NORMATIVE_PATTERN = re.compile(r"\b(shall|must|should|required|may|can)\b", re.IGNORECASE)


def collapse_confusables(text: str) -> str:
    """Normalize unicode confusable characters to their ASCII equivalents."""

    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_requirement_text(text: str) -> str:
    """Return a stable key for deduplicating requirement sentences."""

    text = collapse_confusables(text.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = WORD_BOUNDARY.sub(" ", text)
    return text.strip()


def next_requirement_id(bucket: str, index: int) -> str:
    """Create a deterministic identifier for a requirement entry."""

    prefix = bucket[:1].lower() or "r"
    return f"{prefix}-{index:03d}"


def detect_normative_terms(text: str) -> int:
    """Return the number of normative cue hits in the text."""

    return len(NORMATIVE_PATTERN.findall(text))


def infer_level_from_text(text: str) -> Level:
    """Best-effort level inference for heuristic extraction."""

    lowered = text.lower()
    if re.search(r"\b(shall|must|required)\b", lowered):
        return Level.MUST
    if re.search(r"\b(should|recommended)\b", lowered):
        return Level.SHOULD
    return Level.MAY
