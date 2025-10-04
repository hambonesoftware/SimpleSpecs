"""Specification extraction loop for phase P4."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from ..config import Settings, get_settings
from ..models import ParsedObject, SectionNode, SpecItem
from .llm_client import LLMAdapter

__all__ = ["build_specs_prompt", "extract_specs_for_sections"]

_MAX_SECTION_TEXT = 10_000
_UNIT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mm|cm|m|in|ft|N|kN|MPa|GPa|°C|°F)\b",
    re.IGNORECASE,
)
_STANDARD_PATTERN = re.compile(r"\b(?:ASME|ISO|DIN|ASTM)\b", re.IGNORECASE)
_BULLET_PATTERN = re.compile(r"^\s*(?:[-\u2022*]|\d+(?:\.\d+)*[.)]?)")


def _load_chunks(file_id: str, settings: Settings) -> dict[str, list[str]]:
    target = Path(settings.ARTIFACTS_DIR) / file_id / "chunks" / "chunks.json"
    if not target.exists():
        raise FileNotFoundError("chunks_missing")
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: list(value) for key, value in data.items()}


def _persist_specs(file_id: str, specs: Iterable[SpecItem], settings: Settings) -> None:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "specs"
    base.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in specs]
    with (base / "specs.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _iter_leaves(root: SectionNode) -> Iterable[SectionNode]:
    if not root.children:
        yield root
        return
    for child in root.children:
        yield from _iter_leaves(child)


def _sorted_objects(objects: Iterable[ParsedObject]) -> list[ParsedObject]:
    return sorted(objects, key=lambda obj: ((obj.page_index or 0), obj.order_index))


def _normalize_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    text = re.sub(r"^[-\u2022*]\s+", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*[.)]\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*\s+", "", text)
    while text and text[-1] in ".;:,":
        text = text[:-1]
    return text.strip()


def _parse_llm_response(payload: str) -> list[str]:
    lines: list[str] = []
    for raw in payload.splitlines():
        cleaned = _normalize_line(raw)
        if cleaned:
            lines.append(cleaned)
    return lines


def _fallback_candidates(section_text: str) -> list[str]:
    matches: list[str] = []
    for raw in section_text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if (
            _UNIT_PATTERN.search(stripped)
            or _STANDARD_PATTERN.search(stripped)
            or _BULLET_PATTERN.match(stripped)
        ):
            normalized = _normalize_line(stripped)
            if normalized:
                matches.append(normalized)
        if len(matches) >= 5:
            break
    return matches




def _find_heading_index(section: SectionNode, objects: list[ParsedObject]) -> int | None:
    target = _normalize_line(section.title).lower()
    if not target:
        return None
    for idx, obj in enumerate(objects):
        content = (obj.text or "").strip()
        if not content:
            continue
        normalized = _normalize_line(content).lower()
        if normalized == target:
            return idx
    return None


def _build_fallback_mapping(
    leaves: list[SectionNode],
    chunk_map: dict[str, list[str]],
    ordered_objects: list[ParsedObject],
    order_index: dict[str, int],
) -> dict[str, list[str]]:
    start_positions: list[tuple[str, int, bool]] = []
    for section in leaves:
        object_ids = [oid for oid in chunk_map.get(section.section_id, []) if oid in order_index]
        if object_ids:
            start_positions.append((section.section_id, order_index[object_ids[0]], True))
            continue
        heading_idx = _find_heading_index(section, ordered_objects)
        if heading_idx is not None:
            start_positions.append((section.section_id, heading_idx, False))
    start_positions.sort(key=lambda item: item[1])
    fallback: dict[str, list[str]] = {}
    for idx, (section_id, start_idx, has_chunk) in enumerate(start_positions):
        if has_chunk:
            continue
        end_idx = len(ordered_objects) - 1
        for _, next_start, _ in start_positions[idx + 1 :]:
            if next_start > start_idx:
                end_idx = next_start - 1
                break
        if end_idx < start_idx:
            end_idx = start_idx
        fallback[section_id] = [
            ordered_objects[pos].object_id for pos in range(start_idx, end_idx + 1)
        ]
    if not fallback:
        has_chunks = any(chunk_map.get(section.section_id) for section in leaves)
        if not has_chunks and leaves:
            fallback[leaves[0].section_id] = [obj.object_id for obj in ordered_objects]
    return fallback
def build_specs_prompt(section: SectionNode, text: str) -> str:
    """Construct the deterministic prompt for a section."""

    section_number = section.number or "N/A"
    truncated_text = text[:_MAX_SECTION_TEXT]
    return (
        "You are extracting mechanical engineering specifications.\n"
        f'Section: "{section.title}" (Number: {section_number})\n'
        "Provide a concise bullet list of each mechanical engineering specification found in this section.\n"
        "Return each spec on its own line; do not include commentary.\n\n"
        f"{truncated_text}"
    )


def extract_specs_for_sections(
    file_id: str,
    root: SectionNode,
    objects: list[ParsedObject],
    adapter: LLMAdapter,
) -> list[SpecItem]:
    """Iterate document leaves, run the adapter, and persist specs."""

    settings = get_settings()
    chunk_map = _load_chunks(file_id, settings)
    indexed_objects = {obj.object_id: obj for obj in objects}
    ordered_objects = _sorted_objects(objects)
    order_index = {obj.object_id: idx for idx, obj in enumerate(ordered_objects)}

    specs: list[SpecItem] = []
    seen_pairs: set[tuple[tuple[str, ...], str]] = set()

    leaves = list(_iter_leaves(root))
    fallback_map = _build_fallback_mapping(leaves, chunk_map, ordered_objects, order_index)

    for section in leaves:
        object_ids = chunk_map.get(section.section_id, [])
        if not object_ids:
            object_ids = fallback_map.get(section.section_id, [])
        if not object_ids:
            continue
        sorted_ids = sorted(
            [oid for oid in object_ids if oid in indexed_objects],
            key=lambda oid: order_index[oid],
        )
        if not sorted_ids:
            continue
        section_lines: list[str] = []
        for object_id in sorted_ids:
            obj = indexed_objects[object_id]
            if obj.kind != "text":
                continue
            text = (obj.text or "").strip()
            if text:
                section_lines.append(text)
        if not section_lines:
            continue
        section_text = "\n".join(section_lines)
        prompt = build_specs_prompt(section, section_text)
        try:
            response = adapter.generate(prompt)
        except Exception:
            response = ""
        response_lines = _parse_llm_response(response) if response.strip() else []
        candidates = response_lines or _fallback_candidates(section_text)
        for index, candidate in enumerate(candidates):
            spec_text = candidate
            if not spec_text:
                continue
            spec_id_seed = f"{file_id}|{section.section_id}|{index}|{spec_text}"
            spec_id = hashlib.sha1(spec_id_seed.encode("utf-8")).hexdigest()
            dedup_key = (tuple(sorted_ids), spec_text.lower())
            if dedup_key in seen_pairs:
                continue
            seen_pairs.add(dedup_key)
            specs.append(
                SpecItem(
                    spec_id=spec_id,
                    file_id=file_id,
                    section_id=section.section_id,
                    section_number=section.number,
                    section_title=section.title,
                    spec_text=spec_text,
                    confidence=None,
                    source_object_ids=list(sorted_ids),
                )
            )

    _persist_specs(file_id, specs, settings)
    return specs
