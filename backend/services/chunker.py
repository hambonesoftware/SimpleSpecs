"""Granular chunking helpers for section trees."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import Settings, get_settings
from ..models import PARSED_OBJECT_ADAPTER, ParsedObject, SectionNode, SectionSpan

__all__ = ["compute_section_spans", "load_persisted_chunks", "run_chunking"]


def _extract_text(obj: ParsedObject) -> str:
    """Return textual content for the parsed object if available."""

    return (
        getattr(obj, "text", None)
        or getattr(obj, "content", None)
        or ""
    )


def _normalize_heading_text(text: str) -> str:
    """Normalize heading text for fuzzy comparisons."""

    cleaned = re.sub(r"[\s]+", " ", text or "").strip().lower()
    cleaned = re.sub(r"[^0-9a-z ]+", "", cleaned)
    return cleaned


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
    return [PARSED_OBJECT_ADAPTER.validate_python(item) for item in payload]


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

    initial_nodes: list[SectionNode] = []

    def _collect_initial(node: SectionNode) -> None:
        initial_nodes.append(node)
        for child in node.children:
            _collect_initial(child)

    _collect_initial(root)

    def _span_bounds(node: SectionNode) -> tuple[int | None, int | None]:
        span = node.span
        if span is None or span.start_object is None:
            return (None, None)
        start = object_index.get(span.start_object)
        if start is None:
            return (None, None)
        end = object_index.get(span.end_object) if span.end_object is not None else start
        if end is None:
            end = start
        if end < start:
            start, end = end, start
        return (start, end)

    span_indices: dict[str, tuple[int | None, int | None]] = {
        node.section_id: _span_bounds(node) for node in initial_nodes
    }

    pending_children: dict[str, list[tuple[int, SectionNode]]] = {}
    for node in initial_nodes:
        start_idx, end_idx = span_indices.get(node.section_id, (None, None))
        if start_idx is None or end_idx is None or not node.children:
            continue
        child_ranges: list[tuple[int, int, SectionNode]] = []
        for child in node.children:
            cstart, cend = span_indices.get(child.section_id, (None, None))
            if cstart is None or cend is None:
                continue
            child_ranges.append((cstart, cend, child))
        if not child_ranges:
            continue
        child_ranges.sort(key=lambda item: (item[0], item[1]))
        cursor = start_idx
        gaps: list[tuple[int, int]] = []
        for cstart, cend, _child in child_ranges:
            if cstart > cursor:
                gap_start = cursor
                gap_end = min(cstart - 1, end_idx)
                if gap_end >= gap_start:
                    gaps.append((gap_start, gap_end))
            cursor = max(cursor, cend + 1)
        if cursor <= end_idx:
            gap_start, gap_end = cursor, end_idx
            if gap_end >= gap_start:
                gaps.append((gap_start, gap_end))
        if not gaps:
            continue
        extras: list[tuple[int, SectionNode]] = pending_children.setdefault(node.section_id, [])
        for gap_start, gap_end in gaps:
            new_id = f"{node.section_id}::gap-{gap_start:06d}-{gap_end:06d}"
            if any(child.section_id == new_id for child in node.children):
                continue
            title = f"{node.title} residual"
            extra_node = SectionNode(
                section_id=new_id,
                file_id=node.file_id,
                title=title,
                depth=node.depth + 1,
                number=None,
                span=SectionSpan(
                    start_object=ordered_objects[gap_start].object_id,
                    end_object=ordered_objects[gap_end].object_id,
                ),
                children=[],
            )
            extras.append((gap_start, extra_node))

    if pending_children:
        for node in initial_nodes:
            extras = pending_children.get(node.section_id)
            if not extras:
                continue
            for _, extra in sorted(extras, key=lambda item: item[0]):
                node.children.append(extra)

    leaf_nodes: list[SectionNode] = []
    all_nodes: list[SectionNode] = []

    def _child_start(child: SectionNode) -> int:
        start, _ = _span_bounds(child)
        if start is not None:
            return start
        if child.span and child.span.start_object:
            idx = object_index.get(child.span.start_object)
            if idx is not None:
                return idx
        return len(ordered_objects)

    def _collect(node: SectionNode) -> None:
        all_nodes.append(node)
        if not node.children:
            leaf_nodes.append(node)
            return
        node.children.sort(key=_child_start)
        for child in node.children:
            _collect(child)

    _collect(root)

    leaf_ranges: dict[str, tuple[int, int]] = {}
    anchor_index: dict[str, int] = {}
    ordered_leaf_entries: list[tuple[int, int, str, SectionNode, int | None, int]] = []
    for leaf in leaf_nodes:
        span = leaf.span
        if span is None or span.start_object is None:
            continue
        start_index = object_index.get(span.start_object)
        if start_index is None:
            continue
        end_index = object_index.get(span.end_object) if span.end_object is not None else None
        order_position = (
            min(start_index, end_index)
            if end_index is not None
            else start_index
        )
        anchor_index[leaf.section_id] = start_index
        ordered_leaf_entries.append(
            (order_position, leaf.depth, leaf.section_id, leaf, end_index, start_index)
        )

    ordered_leaf_entries.sort(key=lambda item: (item[0], item[1], item[2]))

    total_objects = len(ordered_objects)
    for idx, (order_pos, _, section_id, leaf, explicit_end, anchor_pos) in enumerate(ordered_leaf_entries):
        next_boundary = total_objects
        for later_idx in range(idx + 1, len(ordered_leaf_entries)):
            candidate_pos = ordered_leaf_entries[later_idx][0]
            if candidate_pos > order_pos:
                next_boundary = candidate_pos
                break
        effective_end = next_boundary - 1 if next_boundary > 0 else -1
        if explicit_end is not None:
            effective_end = min(effective_end, explicit_end)
        anchor_obj = ordered_objects[anchor_pos] if 0 <= anchor_pos < total_objects else None
        anchor_text = _normalize_heading_text(_extract_text(anchor_obj)) if anchor_obj else ""
        title_text = _normalize_heading_text(leaf.title)
        is_heading_anchor = bool(
            anchor_text
            and title_text
            and (anchor_text.startswith(title_text) or title_text.startswith(anchor_text))
        )
        start_inclusive = anchor_pos + 1 if is_heading_anchor else anchor_pos
        if start_inclusive > effective_end:
            continue
        leaf_ranges[section_id] = (start_inclusive, effective_end)

    leaf_chunks: dict[str, list[str]] = {leaf.section_id: [] for leaf in leaf_nodes}

    for index, obj in enumerate(ordered_objects):
        candidates: list[tuple[int, int, str, SectionNode]] = []
        for leaf in leaf_nodes:
            span = leaf_ranges.get(leaf.section_id)
            anchor_pos = anchor_index.get(leaf.section_id)
            if span is None or anchor_pos is None:
                continue
            start_idx, end_idx = span
            if index < start_idx or index > end_idx:
                continue
            distance = index - anchor_pos
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

    assigned_leaf_ids = {oid for chunk in leaf_chunks.values() for oid in chunk}
    if root.section_id in result:
        missing_ids = [
            obj.object_id
            for obj in ordered_objects
            if obj.object_id not in assigned_leaf_ids
        ]
        if missing_ids:
            combined = list(dict.fromkeys(result[root.section_id] + missing_ids))
            combined.sort(key=lambda oid: object_index.get(oid, len(ordered_objects)))
            result[root.section_id] = combined

    for node in all_nodes:
        result.setdefault(node.section_id, [])

    return result
