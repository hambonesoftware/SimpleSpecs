"""Granular chunking helpers for section trees."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Settings, get_settings
from ..models import ParsedObject, SectionNode

__all__ = ["compute_section_spans", "load_persisted_chunks", "run_chunking"]


def _sorted_objects(objects: list[ParsedObject]) -> list[ParsedObject]:
    return sorted(
        objects,
        key=lambda obj: ((obj.page_index or 0), obj.order_index),
    )


def _load_parsed_objects(file_id: str, settings: Settings) -> list[ParsedObject]:
    objects_path = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    if not objects_path.exists():
        raise FileNotFoundError("parsed_objects_missing")
    with objects_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [ParsedObject.model_validate(item) for item in payload]


def _load_sections(file_id: str, settings: Settings) -> SectionNode:
    sections_path = Path(settings.ARTIFACTS_DIR) / file_id / "headers" / "sections.json"
    if not sections_path.exists():
        raise FileNotFoundError("sections_missing")
    with sections_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return SectionNode.model_validate(payload)


def _persist_chunks(file_id: str, mapping: dict[str, list[str]], settings: Settings) -> None:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "chunks"
    base.mkdir(parents=True, exist_ok=True)
    target = base / "chunks.json"
    with target.open("w", encoding="utf-8") as handle:
        json.dump(mapping, handle, indent=2)


def load_persisted_chunks(file_id: str, settings: Settings | None = None) -> dict[str, list[str]]:
    """Load persisted chunk assignments from disk."""

    settings = settings or get_settings()
    target = Path(settings.ARTIFACTS_DIR) / file_id / "chunks" / "chunks.json"
    if not target.exists():
        raise FileNotFoundError("chunks_missing")
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: list(value) for key, value in data.items()}


def run_chunking(file_id: str, settings: Settings | None = None) -> dict[str, list[str]]:
    """Compute and persist section chunks for the provided file identifier."""

    settings = settings or get_settings()
    objects = _load_parsed_objects(file_id, settings)
    sections = _load_sections(file_id, settings)
    mapping = compute_section_spans(sections, objects)
    _persist_chunks(file_id, mapping, settings)
    return mapping


def compute_section_spans(root: SectionNode, objects: list[ParsedObject]) -> dict[str, list[str]]:
    """Return ordered object identifiers for every section in the tree.

    The function enforces non-overlapping assignments across leaf sections using
    the deterministic tie-breaker described in the phase plan. Parent sections
    receive the ordered concatenation of their descendant leaf chunks.
    """

    ordered_objects = _sorted_objects(list(objects))
    object_index: dict[str, int] = {obj.object_id: idx for idx, obj in enumerate(ordered_objects)}

    leaf_nodes: list[SectionNode] = []
    all_nodes: list[SectionNode] = []

    def _collect(node: SectionNode) -> None:
        all_nodes.append(node)
        if not node.children:
            leaf_nodes.append(node)
        for child in node.children:
            _collect(child)

    _collect(root)

    leaf_ranges: dict[str, tuple[int, int]] = {}
    for leaf in leaf_nodes:
        start_id = leaf.span.start_object
        end_id = leaf.span.end_object
        if start_id is None or end_id is None:
            continue
        start_index = object_index.get(start_id)
        end_index = object_index.get(end_id)
        if start_index is None or end_index is None:
            continue
        low, high = sorted((start_index, end_index))
        leaf_ranges[leaf.section_id] = (low, high)

    leaf_chunks: dict[str, list[str]] = {leaf.section_id: [] for leaf in leaf_nodes}

    for index, obj in enumerate(ordered_objects):
        candidates: list[tuple[int, int, str, SectionNode]] = []
        for leaf in leaf_nodes:
            span = leaf_ranges.get(leaf.section_id)
            if span is None:
                continue
            start_idx, end_idx = span
            if index < start_idx or index > end_idx:
                continue
            distance = index - start_idx
            candidates.append((distance, leaf.depth, leaf.section_id, leaf))
        if not candidates:
            continue
        _, _, _, chosen_leaf = min(candidates, key=lambda item: (item[0], item[1], item[2]))
        leaf_chunks[chosen_leaf.section_id].append(obj.object_id)

    result: dict[str, list[str]] = {}

    def _build(node: SectionNode) -> list[str]:
        if not node.children:
            chunk = list(leaf_chunks.get(node.section_id, []))
            result[node.section_id] = chunk
            return list(chunk)
        aggregate: list[str] = []
        for child in node.children:
            aggregate.extend(_build(child))
        chunk_copy = list(aggregate)
        result[node.section_id] = chunk_copy
        return aggregate

    _build(root)

    for node in all_nodes:
        result.setdefault(node.section_id, [])

    return result
