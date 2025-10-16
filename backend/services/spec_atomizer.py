"""Rule-based specification atomizer."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, Sequence

from ..models import SpecItem

_SPEC_TRIGGER_WORDS = ("shall", "must", "should", "required", "ensure", "provide", "include")
_VALUE_UNIT_RE = re.compile(
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>°\s?[CF]|deg\s?[CF]|mm|cm|m|in|ft|kg|g|lb|lbs|psi|bar|vdc|vac|kv|v|amp|amps|a|ma|hz|rpm|%)",
    re.IGNORECASE,
)
_UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    "mm": ("mm", 1.0),
    "cm": ("mm", 10.0),
    "m": ("mm", 1000.0),
    "in": ("mm", 25.4),
    "ft": ("mm", 304.8),
    "kg": ("kg", 1.0),
    "g": ("kg", 0.001),
    "lb": ("lb", 1.0),
    "lbs": ("lb", 1.0),
    "psi": ("psi", 1.0),
    "bar": ("bar", 1.0),
    "v": ("V", 1.0),
    "kv": ("V", 1000.0),
    "vdc": ("VDC", 1.0),
    "vac": ("VAC", 1.0),
    "a": ("A", 1.0),
    "amp": ("A", 1.0),
    "amps": ("A", 1.0),
    "ma": ("A", 0.001),
    "hz": ("Hz", 1.0),
    "rpm": ("RPM", 1.0),
    "%": ("%", 1.0),
}
_TEMPERATURE_UNITS = {"°c", "degc", "c"}
_TEMPERATURE_F_UNITS = {"°f", "degf", "f"}
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dimensional": (
        "length",
        "width",
        "height",
        "diameter",
        "thickness",
        "spacing",
        "clearance",
        "distance",
        "depth",
    ),
    "electrical": (
        "voltage",
        "current",
        "power",
        "watt",
        "phase",
        "supply",
        "volts",
        "amps",
    ),
    "controls": (
        "controller",
        "plc",
        "relay",
        "sensor",
        "io",
        "i/o",
        "modbus",
        "ethernet",
        "control",
    ),
    "software": (
        "software",
        "firmware",
        "version",
        "api",
        "protocol",
        "ui",
    ),
    "project_management": (
        "training",
        "documentation",
        "schedule",
        "timeline",
        "delivery",
        "commissioning",
        "maintenance",
    ),
}
_UNIT_CATEGORY_HINT = {
    "mm": "dimensional",
    "kg": "dimensional",
    "lb": "dimensional",
    "degc": "dimensional",
    "v": "electrical",
    "vdc": "electrical",
    "vac": "electrical",
    "a": "electrical",
    "hz": "electrical",
    "rpm": "controls",
}


def _clean_line(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^[\-\u2022*]+\s*", "", cleaned)
    cleaned = re.sub(r"^\d+(?:\.\d+)*[.)]\s*", "", cleaned)
    return cleaned.strip()


def _spec_id(file_id: str, section_id: str, text: str) -> str:
    digest = hashlib.sha1(f"{file_id}:{section_id}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"spec-{digest}"


def _normalize_unit(match: re.Match[str]) -> tuple[str | None, float | None, str | None]:
    raw_value = match.group("value")
    raw_unit = match.group("unit").replace(" ", "")
    raw_token = raw_unit.lower()
    value = float(raw_value)
    if raw_token in _TEMPERATURE_UNITS:
        return f"{raw_value} {match.group('unit').strip()}", value, "degC"
    if raw_token in _TEMPERATURE_F_UNITS:
        celsius = (value - 32.0) * 5.0 / 9.0
        return f"{raw_value} {match.group('unit').strip()}", round(celsius, 4), "degC"
    conversion = _UNIT_CONVERSIONS.get(raw_token)
    if not conversion:
        return f"{raw_value} {match.group('unit').strip()}", value, raw_unit
    unit, factor = conversion
    return f"{raw_value} {match.group('unit').strip()}", round(value * factor, 4), unit


def _classify(text: str, normalized_unit: str | None) -> str:
    if normalized_unit:
        token = normalized_unit.lower()
        hinted = _UNIT_CATEGORY_HINT.get(token)
        if hinted:
            return hinted
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.isalpha():
                pattern = rf"\b{re.escape(keyword)}\b"
                if re.search(pattern, lowered):
                    return category
            else:
                if keyword in lowered:
                    return category
    return "general"


def _confidence(text: str, has_value: bool, category: str) -> float:
    lowered = text.lower()
    base = 0.5
    if any(trigger in lowered for trigger in ("shall", "must", "required")):
        base = 0.9
    elif any(trigger in lowered for trigger in ("should", "ensure", "include")):
        base = 0.75
    elif _VALUE_UNIT_RE.search(text):
        base = 0.65
    if has_value:
        base += 0.05
    if category != "general":
        base += 0.05
    return round(min(base, 1.0), 2)


def _candidate_lines(lines: Iterable[str]) -> list[str]:
    candidates: list[str] = []
    for raw in lines:
        cleaned = _clean_line(raw)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(trigger in lowered for trigger in _SPEC_TRIGGER_WORDS) or _VALUE_UNIT_RE.search(cleaned):
            candidates.append(cleaned)
    return candidates


def atomize_section_text(
    *,
    file_id: str,
    section_id: str,
    section_title: str,
    section_number: str | None,
    lines: Sequence[str],
    source_object_ids: Sequence[str] | None = None,
) -> list[SpecItem]:
    """Return ``SpecItem`` entries extracted from *lines* for a section."""

    object_ids = [str(item) for item in (source_object_ids or [])]
    specs: list[SpecItem] = []
    for line in _candidate_lines(lines):
        match = _VALUE_UNIT_RE.search(line)
        raw_value: str | None = None
        normalized_value: float | None = None
        normalized_unit: str | None = None
        if match:
            raw_value, normalized_value, normalized_unit = _normalize_unit(match)
        category = _classify(line, normalized_unit)
        confidence = _confidence(line, normalized_value is not None, category)
        spec = SpecItem(
            spec_id=_spec_id(file_id, section_id, line),
            file_id=file_id,
            section_id=section_id,
            section_title=section_title,
            spec_text=line,
            section_number=section_number,
            source_object_ids=list(object_ids),
            confidence=confidence,
            raw_value=raw_value,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            category=category,
        )
        specs.append(spec)
    return specs
