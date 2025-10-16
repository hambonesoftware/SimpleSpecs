"""Section-aware chunking utilities."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ..config import Settings, get_settings
from ..models import PARSED_OBJECT_ADAPTER, ParsedObject, SectionNode

__all__ = [
    "SectionChunk",
    "build_section_chunks",
    "compute_section_spans",
    "load_persisted_chunks",
    "load_chunk_records",
    "run_chunking",
]


@dataclass(slots=True)
class SectionChunk:
    """Single chunk produced for a document section."""

    section_id: str
    header_path: str
    depth: int
    object_ids: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "header_path": self.header_path,
            "depth": self.depth,
            "object_ids": list(self.object_ids),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "SectionChunk":
        section_id = str(payload.get("section_id") or "")
        header_path = str(payload.get("header_path") or section_id or "")
        depth = int(payload.get("depth") or 0)
        object_ids = [str(item) for item in payload.get("object_ids", [])]
        return cls(section_id=section_id or header_path, header_path=header_path, depth=depth, object_ids=object_ids)


def _sorted_objects(objects: Iterable[ParsedObject]) -> list[ParsedObject]:
    return sorted(objects, key=lambda obj: ((obj.page_index or 0), obj.order_index))


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip().lower()


def _segment_from_node(node: SectionNode) -> str:
    number = (node.number or "").strip()
    title = (node.title or "").strip()
    if number and title:
        return f"{number} {title}"
    if title:
        return title
    if number:
        return number
    return node.section_id


def _looks_like_heading(obj: ParsedObject, node: SectionNode) -> bool:
    object_text = _normalize(getattr(obj, "text", ""))
    title = _normalize(node.title)
    if not object_text or not title:
        return False
    return object_text.startswith(title) or title.startswith(object_text)


def _leaf_object_ids(
    node: SectionNode,
    ordered_objects: Sequence[ParsedObject],
    index_map: dict[str, int],
) -> list[str]:
    span = node.span
    if span is None or span.start_object is None:
        return []
    start = index_map.get(span.start_object)
    if start is None:
        return []
    end = index_map.get(span.end_object) if span.end_object else start
    if end is None:
        end = start
    if end < start:
        start, end = end, start
    result: list[str] = []
    for idx in range(start, end + 1):
        obj = ordered_objects[idx]
        if idx == start and _looks_like_heading(obj, node):
            continue
        result.append(obj.object_id)
    return result


def _dedupe_by_order(object_ids: Iterable[str], index_map: dict[str, int]) -> list[str]:
    seen: set[str] = set()
    ordered = sorted(object_ids, key=lambda oid: index_map.get(oid, 10**9))
    result: list[str] = []
    for oid in ordered:
        if oid in seen:
            continue
        seen.add(oid)
        result.append(oid)
    return result


def build_section_chunks(root: SectionNode, objects: list[ParsedObject]) -> list[SectionChunk]:
    """Return a ``SectionChunk`` for every section node."""

    ordered_objects = _sorted_objects(objects)
    index_map = {obj.object_id: idx for idx, obj in enumerate(ordered_objects)}
    chunks: list[SectionChunk] = []

    def visit(node: SectionNode, ancestors: list[str]) -> list[str]:
        segment = _segment_from_node(node)
        header_path_parts = ancestors + [segment]
        header_path = " / ".join(part for part in header_path_parts if part)
        if node.children:
            aggregate: list[str] = []
            for child in node.children:
                aggregate.extend(visit(child, header_path_parts))
            object_ids = _dedupe_by_order(aggregate, index_map)
        else:
            object_ids = _leaf_object_ids(node, ordered_objects, index_map)
        chunk = SectionChunk(
            section_id=node.section_id,
            header_path=header_path or node.section_id,
            depth=node.depth,
            object_ids=object_ids,
        )
        chunks.append(chunk)
        return list(chunk.object_ids)

    visit(root, [])
    return chunks


def compute_section_spans(root: SectionNode, objects: list[ParsedObject]) -> dict[str, list[str]]:
    """Backward compatible helper returning object ids keyed by section id."""

    chunks = build_section_chunks(root, objects)
    return {chunk.section_id: list(chunk.object_ids) for chunk in chunks}


def _persist_chunks(file_id: str, chunks: Sequence[SectionChunk], settings: Settings) -> None:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "chunks"
    base.mkdir(parents=True, exist_ok=True)
    payload = {chunk.section_id: list(chunk.object_ids) for chunk in chunks}
    with (base / "chunks.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_chunk_records(file_id: str, settings: Settings | None = None) -> list[SectionChunk]:
    """Return persisted ``SectionChunk`` entries for *file_id*."""

    settings = settings or get_settings()
    target = Path(settings.ARTIFACTS_DIR) / file_id / "chunks" / "chunks.json"
    if not target.exists():
        raise FileNotFoundError("chunks_missing")
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        records: list[SectionChunk] = []
        for section_id, object_ids in data.items():
            records.append(
                SectionChunk(
                    section_id=section_id,
                    header_path=section_id,
                    depth=0,
                    object_ids=[str(item) for item in object_ids],
                )
            )
        return records
    if isinstance(data, list):
        return [SectionChunk.from_payload(item) for item in data]
    raise ValueError("chunks_payload_invalid")


def load_persisted_chunks(file_id: str, settings: Settings | None = None) -> dict[str, list[str]]:
    """Load persisted chunks keyed by section identifier."""

    records = load_chunk_records(file_id, settings=settings)
    return {record.section_id: list(record.object_ids) for record in records}


def run_chunking(file_id: str, settings: Settings | None = None) -> dict[str, list[str]]:
    """Compute and persist section chunks for the provided file identifier."""

    settings = settings or get_settings()
    objects_path = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    sections_path = Path(settings.ARTIFACTS_DIR) / file_id / "headers" / "sections.json"
    if not objects_path.exists():
        raise FileNotFoundError("parsed_objects_missing")
    if not sections_path.exists():
        raise FileNotFoundError("sections_missing")
    with objects_path.open("r", encoding="utf-8") as handle:
        raw_objects = json.load(handle)
    with sections_path.open("r", encoding="utf-8") as handle:
        raw_sections = json.load(handle)
    objects = [PARSED_OBJECT_ADAPTER.validate_python(obj) for obj in raw_objects]
    root = SectionNode.model_validate(raw_sections)
    chunks = build_section_chunks(root, objects)
    _persist_chunks(file_id, chunks, settings)
    return {chunk.section_id: list(chunk.object_ids) for chunk in chunks}
