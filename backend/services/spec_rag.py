"""RAG extraction, indexing, and search helpers for specification chunks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ..config import Settings, get_settings
from ..logging import get_logger
from ..models import PARSED_OBJECT_ADAPTER, ParsedObject, SectionNode, SpecItem
from .chunker import SectionChunk, build_section_chunks
from .headers import load_persisted_headers
from .search import ChunkRecord, HybridSearch
from .spec_atomizer import atomize_section_text
from .embeddings import EmbeddingService
from .index_store import IndexStore

__all__ = [
    "extract_specs",
    "load_spec_items",
    "index_specs",
    "search_specs",
    "export_specs",
]


logger = get_logger(__name__)


@dataclass(slots=True)
class _SectionInfo:
    node: SectionNode
    chunk: SectionChunk


def _load_parsed_objects(file_id: str, settings: Settings) -> list[ParsedObject]:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    if not base.exists():
        raise FileNotFoundError("parsed_objects_missing")
    with base.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [PARSED_OBJECT_ADAPTER.validate_python(item) for item in payload]


def _persist_spec_items(file_id: str, specs: Sequence[SpecItem], settings: Settings) -> None:
    target_dir = Path(settings.ARTIFACTS_DIR) / file_id / "specs"
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = [spec.model_dump(mode="json") for spec in specs]
    with (target_dir / "specs.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _persist_debug_artifacts(
    file_id: str,
    sections_payload: Sequence[dict[str, object]],
    specs_payload: Sequence[dict[str, object]],
) -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    sections_path = debug_dir / f"sections_{file_id}.jsonl"
    specs_path = debug_dir / f"specs_{file_id}.jsonl"
    with sections_path.open("w", encoding="utf-8") as handle:
        for record in sections_payload:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with specs_path.open("w", encoding="utf-8") as handle:
        for record in specs_payload:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _collect_section_info(root: SectionNode, objects: list[ParsedObject]) -> list[_SectionInfo]:
    chunk_records = build_section_chunks(root, objects)
    node_map: dict[str, SectionNode] = {}

    def visit(node: SectionNode) -> None:
        node_map[node.section_id] = node
        for child in node.children:
            visit(child)

    visit(root)
    info: list[_SectionInfo] = []
    for chunk in chunk_records:
        node = node_map.get(chunk.section_id)
        if not node:
            continue
        info.append(_SectionInfo(node=node, chunk=chunk))
    return info


def extract_specs(
    file_id: str,
    *,
    settings: Settings | None = None,
    persist: bool = True,
) -> list[SpecItem]:
    """Run deterministic atomization across all section chunks."""

    resolved = settings or get_settings()
    root = load_persisted_headers(file_id)
    objects = _load_parsed_objects(file_id, resolved)
    object_map = {obj.object_id: obj for obj in objects}

    specs: list[SpecItem] = []
    debug_sections: list[dict[str, object]] = []
    debug_specs: list[dict[str, object]] = []
    for info in _collect_section_info(root, objects):
        if info.node.section_id == root.section_id:
            continue
        lines: list[str] = []
        for object_id in info.chunk.object_ids:
            obj = object_map.get(object_id)
            if not obj:
                continue
            text = (obj.text or "").strip()
            if not text:
                continue
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
        if not lines:
            continue
        extracted = atomize_section_text(
            file_id=file_id,
            section_id=info.node.section_id,
            section_title=info.node.title,
            section_number=info.node.number,
            lines=lines,
            source_object_ids=info.chunk.object_ids,
        )
        if resolved.RAG_DEBUG:
            debug_sections.append(
                {
                    "section_id": info.node.section_id,
                    "header_path": info.chunk.header_path,
                    "section_title": info.node.title,
                    "section_number": info.node.number,
                    "object_ids": list(info.chunk.object_ids),
                    "line_count": len(lines),
                }
            )
        for spec in extracted:
            spec.header_path = info.chunk.header_path
            specs.append(spec)
            if resolved.RAG_DEBUG:
                debug_specs.append(spec.model_dump(mode="json"))
    if persist:
        _persist_spec_items(file_id, specs, resolved)
    if resolved.RAG_DEBUG:
        _persist_debug_artifacts(file_id, debug_sections, debug_specs)
        logger.debug(
            "rag.extract_specs debug artifacts persisted for %s",
            file_id,
        )
        logger.info(
            "Spec extraction complete for %s: %d sections, %d specs",
            file_id,
            len(debug_sections),
            len(debug_specs),
        )
    return specs


def load_spec_items(file_id: str, *, settings: Settings | None = None) -> list[SpecItem]:
    resolved = settings or get_settings()
    target = Path(resolved.ARTIFACTS_DIR) / file_id / "specs" / "specs.json"
    if not target.exists():
        raise FileNotFoundError("specs_missing")
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [SpecItem.model_validate(item) for item in payload]


def _build_records(specs: Sequence[SpecItem]) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    for spec in specs:
        metadata = {
            "file_id": spec.file_id,
            "spec_id": spec.spec_id,
            "section_id": spec.section_id,
            "section_title": spec.section_title,
            "section_number": spec.section_number,
            "header_path": spec.header_path,
            "normalized_unit": spec.normalized_unit,
            "normalized_value": spec.normalized_value,
            "raw_value": spec.raw_value,
            "category": spec.category,
        }
        records.append(
            ChunkRecord(
                chunk_id=spec.spec_id,
                text=spec.spec_text,
                metadata=metadata,
            )
        )
    return records


def index_specs(
    file_id: str,
    *,
    settings: Settings | None = None,
    specs: Sequence[SpecItem] | None = None,
) -> HybridSearch:
    """Build and persist the hybrid search index for a file's specifications."""

    resolved = settings or get_settings()
    spec_items = list(specs) if specs is not None else load_spec_items(file_id, settings=resolved)
    records = _build_records(spec_items)
    embedding = EmbeddingService(resolved)
    index_store = IndexStore(embedding.dimension, index_name=f"specs_{file_id}", settings=resolved)
    searcher = HybridSearch(embedding_service=embedding, index_store=index_store, settings=resolved)
    searcher.index(records)
    if resolved.RAG_DEBUG:
        logger.info("Indexed %d spec records for %s", len(records), file_id)
    return searcher


def search_specs(
    file_id: str,
    query: str,
    *,
    top_k: int = 5,
    settings: Settings | None = None,
) -> list[dict[str, object]]:
    """Execute a hybrid search query for a file's indexed specs."""

    resolved = settings or get_settings()
    specs = load_spec_items(file_id, settings=resolved)
    searcher = index_specs(file_id, settings=resolved, specs=specs)
    return searcher.search(query, k=top_k)


def export_specs(file_id: str, *, settings: Settings | None = None) -> dict[str, object]:
    """Return a serializable export payload for persisted specs."""

    resolved = settings or get_settings()
    specs = load_spec_items(file_id, settings=resolved)
    return {
        "file_id": file_id,
        "specs": [spec.model_dump(mode="json") for spec in specs],
    }
