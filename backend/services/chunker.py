"""Granular chunking helpers for section trees."""
from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..models import ParsedObject, SectionNode

__all__ = ["compute_section_spans", "load_persisted_chunks", "run_chunking"]


def _extract_text(obj: ParsedObject) -> str:
    """Return textual content for the parsed object if available."""

    return (
        getattr(obj, "text", None)
        or getattr(obj, "content", None)
        or ""
    )


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_TOKEN_RE = re.compile(r"\w+")


def _normalize_heading_text(text: str) -> str:
    """Normalize heading text for fuzzy comparisons."""

    cleaned = re.sub(r"[\s]+", " ", (text or "")).strip().lower()
    cleaned = re.sub(r"^[0-9ivxlcdm\.\)\(\- ]+", "", cleaned)
    cleaned = re.sub(r"[^0-9a-z ]+", "", cleaned)
    return cleaned.strip()


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


def _estimate_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


@dataclass
class _ChunkComputationResult:
    mapping: dict[str, list[str]]
    ordered_objects: list[ParsedObject]
    object_index: dict[str, int]
    parent_map: dict[str, SectionNode | None]
    section_lookup: dict[str, SectionNode]


def _persist_chunks(
    file_id: str,
    mapping: dict[str, list[str]],
    canonical: list[dict[str, Any]],
    shards: list[dict[str, Any]],
    settings: Settings,
) -> None:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "chunks"
    base.mkdir(parents=True, exist_ok=True)
    target = base / "chunks.json"
    with target.open("w", encoding="utf-8") as handle:
        json.dump(mapping, handle, indent=2)
    canonical_target = base / "canonical.json"
    with canonical_target.open("w", encoding="utf-8") as handle:
        json.dump(canonical, handle, indent=2)
    shards_target = base / "shards.json"
    with shards_target.open("w", encoding="utf-8") as handle:
        json.dump(shards, handle, indent=2)


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
    computation = _compute_chunks(sections, objects)
    canonical, shards = _build_canonical_artifacts(computation)
    _persist_chunks(file_id, computation.mapping, canonical, shards, settings)
    return computation.mapping


def compute_section_spans(root: SectionNode, objects: list[ParsedObject]) -> dict[str, list[str]]:
    """Return ordered object identifiers for every section in the tree.

    The function enforces non-overlapping assignments across leaf sections using
    the deterministic tie-breaker described in the phase plan. Parent sections
    receive the ordered concatenation of their descendant leaf chunks.
    """

    return _compute_chunks(root, objects).mapping


def _compute_chunks(root: SectionNode, objects: list[ParsedObject]) -> _ChunkComputationResult:
    ordered_objects = _sorted_objects(list(objects))
    object_index: dict[str, int] = {obj.object_id: idx for idx, obj in enumerate(ordered_objects)}

    parent_map: dict[str, SectionNode | None] = {root.section_id: None}
    section_lookup: dict[str, SectionNode] = {}
    leaf_nodes: list[SectionNode] = []
    all_nodes: list[SectionNode] = []

    def _collect(node: SectionNode, parent: SectionNode | None) -> None:
        parent_map[node.section_id] = parent
        section_lookup[node.section_id] = node
        all_nodes.append(node)
        if not node.children:
            leaf_nodes.append(node)
        for child in node.children:
            _collect(child, node)

    _collect(root, None)

    total_objects = len(ordered_objects)
    intervals: list[dict[str, Any]] = []
    for leaf in leaf_nodes:
        span = leaf.span
        if span is None or span.start_object is None:
            continue
        anchor_idx = object_index.get(span.start_object)
        if anchor_idx is None:
            continue
        anchor_obj = ordered_objects[anchor_idx] if 0 <= anchor_idx < total_objects else None
        anchor_text = _normalize_heading_text(_extract_text(anchor_obj)) if anchor_obj else ""
        title_text = _normalize_heading_text(leaf.title)
        start_idx = anchor_idx + 1 if anchor_text and title_text and anchor_text == title_text else anchor_idx
        explicit_end: int | None = None
        if span.end_object:
            end_idx = object_index.get(span.end_object)
            if end_idx is not None:
                explicit_end = min(end_idx + 1, total_objects)
        container_end = _resolve_container_end(leaf, parent_map, object_index, total_objects)
        intervals.append(
            {
                "leaf": leaf,
                "anchor_idx": anchor_idx,
                "start": max(0, min(start_idx, total_objects)),
                "explicit_end": explicit_end,
                "container_end": container_end,
            }
        )

    intervals.sort(
        key=lambda item: (
            item["anchor_idx"],
            item["leaf"].depth,
            item["leaf"].section_id,
        )
    )

    for idx, info in enumerate(intervals):
        candidates = [total_objects]
        if info.get("explicit_end") is not None:
            candidates.append(info["explicit_end"])
        if info.get("container_end") is not None:
            candidates.append(info["container_end"])
        if idx + 1 < len(intervals):
            candidates.append(intervals[idx + 1]["anchor_idx"])
        end_exclusive = min(candidates)
        end_exclusive = max(info["start"], min(end_exclusive, total_objects))
        info["end"] = end_exclusive

    prev_end = 0
    for info in intervals:
        start = max(info["start"], prev_end)
        end = max(start, info.get("end", start))
        info["start"] = start
        info["end"] = min(end, total_objects)
        prev_end = info["end"]

    leaf_chunks: dict[str, list[str]] = {leaf.section_id: [] for leaf in leaf_nodes}
    for info in intervals:
        start_idx = info["start"]
        end_idx = info["end"]
        if start_idx >= end_idx:
            leaf_chunks[info["leaf"].section_id] = []
            continue
        chunk_ids = [
            ordered_objects[pos].object_id
            for pos in range(start_idx, min(end_idx, total_objects))
        ]
        leaf_chunks[info["leaf"].section_id] = chunk_ids

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

    return _ChunkComputationResult(
        mapping=result,
        ordered_objects=ordered_objects,
        object_index=object_index,
        parent_map=parent_map,
        section_lookup=section_lookup,
    )


def _resolve_container_end(
    node: SectionNode,
    parent_map: dict[str, SectionNode | None],
    object_index: dict[str, int],
    default_end: int,
) -> int:
    current: SectionNode | None = node
    while current is not None:
        span = current.span
        if span and span.end_object:
            end_idx = object_index.get(span.end_object)
            if end_idx is not None:
                return min(end_idx + 1, default_end)
        current = parent_map.get(current.section_id)
    return default_end


def _build_header_path(
    section_id: str,
    lookup: dict[str, SectionNode],
    parent_map: dict[str, SectionNode | None],
) -> list[str]:
    titles: list[str] = []
    current = lookup.get(section_id)
    while current is not None:
        title = (current.title or "").strip()
        if title:
            titles.append(title)
        current = parent_map.get(current.section_id)
    titles.reverse()
    if titles:
        return titles[:-1]
    return []


def _build_canonical_artifacts(
    computation: _ChunkComputationResult,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    object_lookup = {obj.object_id: obj for obj in computation.ordered_objects}
    canonical: list[dict[str, Any]] = []
    shards: list[dict[str, Any]] = []
    for section_id, node in computation.section_lookup.items():
        object_ids = computation.mapping.get(section_id, [])
        positions = [
            computation.object_index[oid]
            for oid in object_ids
            if oid in computation.object_index
        ]
        object_span = (
            [min(positions), max(positions) + 1]
            if positions
            else None
        )
        page_candidates: list[int] = []
        for oid in object_ids:
            obj = object_lookup.get(oid)
            if obj and obj.page_index is not None:
                page_candidates.append(obj.page_index)
        span = node.span
        if not page_candidates and span:
            if span.page_start is not None:
                page_candidates.append(span.page_start)
            if span.page_end is not None:
                page_candidates.append(span.page_end)
        page_span = (
            [min(page_candidates), max(page_candidates)]
            if page_candidates
            else None
        )
        body_lines: list[str] = []
        outbound: list[str] = []
        for oid in object_ids:
            obj = object_lookup.get(oid)
            if not obj:
                continue
            text = obj.clean_text
            if text:
                body_lines.append(text)
            kind_lower = obj.kind.lower() if isinstance(obj.kind, str) else ""
            if kind_lower in {"table", "figure", "image", "chart"}:
                outbound.append(oid)
        header_text = (node.title or "").strip()
        if body_lines:
            clean_text = "\n".join([header_text] + body_lines) if header_text else "\n".join(body_lines)
        else:
            clean_text = header_text
        token_count = _estimate_tokens(clean_text)
        header_path = _build_header_path(
            section_id, computation.section_lookup, computation.parent_map
        )
        parent = computation.parent_map.get(section_id)
        entry = {
            "section_id": section_id,
            "file_id": node.file_id,
            "parent_section_id": parent.section_id if parent else None,
            "header_text": header_text,
            "header_path": header_path,
            "level": node.depth,
            "page_span": page_span,
            "object_index_span": object_span,
            "token_count": token_count,
            "text": clean_text,
            "source_object_ids": object_ids,
            "outbound_object_ids": outbound,
            "hash": hashlib.sha1(clean_text.encode("utf-8")).hexdigest(),
        }
        canonical.append(entry)
        shards.extend(_build_shards_for_entry(entry))
    return canonical, shards


def _split_into_shards(
    text: str,
    target_tokens: int = 300,
    min_tokens: int = 200,
    max_tokens: int = 400,
    overlap_ratio: float = 0.15,
) -> list[tuple[int, int, str, int]]:
    stripped = text.strip()
    if not stripped:
        return []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(stripped) if s.strip()]
    if not sentences:
        sentences = [stripped]
    tokens_per_sentence = [max(1, _estimate_tokens(sentence)) for sentence in sentences]
    total = len(sentences)
    shards: list[tuple[int, int, str, int]] = []
    start = 0
    while start < total:
        token_sum = 0
        end = start
        while end < total and token_sum < target_tokens:
            token_sum += tokens_per_sentence[end]
            end += 1
            if token_sum >= max_tokens:
                break
        while end < total and token_sum < min_tokens:
            token_sum += tokens_per_sentence[end]
            end += 1
            if token_sum >= max_tokens:
                break
        if end == start:
            end = min(start + 1, total)
            token_sum = tokens_per_sentence[start]
        shard_text = " ".join(sentences[start:end]).strip()
        shards.append((start, end, shard_text, token_sum))
        if end >= total:
            break
        overlap_tokens = max(1, int(token_sum * overlap_ratio)) if token_sum > 0 else 0
        if overlap_tokens <= 0:
            start = end
            continue
        token_back = 0
        new_start = end
        while new_start > start:
            new_start -= 1
            token_back += tokens_per_sentence[new_start]
            if token_back >= overlap_tokens:
                break
        if new_start == start:
            start = end
        else:
            start = new_start
    return shards


def _build_shards_for_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    header_segments = [seg for seg in entry.get("header_path", []) if seg]
    header_segments.append(entry.get("header_text", ""))
    prefix = " > ".join([seg for seg in header_segments if seg])
    lines = entry.get("text", "").splitlines()
    body_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else entry.get("text", "").strip()
    if not body_text:
        body_text = entry.get("header_text", "").strip()
    shard_chunks = _split_into_shards(body_text)
    if not shard_chunks:
        shard_chunks = [(0, 1, body_text, _estimate_tokens(body_text))]
    shards: list[dict[str, Any]] = []
    for idx, (_, _, chunk_text, _) in enumerate(shard_chunks):
        chunk_body = chunk_text.strip()
        if chunk_body:
            shard_text = f"{prefix}\n\n{chunk_body}" if prefix else chunk_body
        else:
            shard_text = prefix
        shard_payload = {
            "shard_id": f"{entry['section_id']}-shard-{idx:03d}",
            "parent_section_id": entry.get("parent_section_id"),
            "section_id": entry["section_id"],
            "file_id": entry["file_id"],
            "header_path": entry.get("header_path", []),
            "header_text": entry.get("header_text"),
            "text": shard_text,
            "token_count": _estimate_tokens(shard_text),
            "object_index_span": entry.get("object_index_span"),
            "page_span": entry.get("page_span"),
            "hash": hashlib.sha1(shard_text.encode("utf-8")).hexdigest(),
        }
        shards.append(shard_payload)
    return shards
