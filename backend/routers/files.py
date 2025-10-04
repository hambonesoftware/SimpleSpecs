"""File-related routes that complement ingestion."""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..models import PARSED_OBJECT_ADAPTER, ParsedObject, SectionNode, SpecItem
from ..services.chunker import load_persisted_chunks, run_chunking
from ..services.headers import load_persisted_headers, run_header_discovery
from ..services.specs import extract_specs_for_sections

files_router = APIRouter(prefix="", tags=["files"])


def _iter_leaves(node: SectionNode) -> Iterator[SectionNode]:
    if not node.children:
        yield node
        return
    for child in node.children:
        yield from _iter_leaves(child)


def _compute_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sorted_specs(specs: Iterable[SpecItem]) -> list[SpecItem]:
    return sorted(specs, key=lambda item: (item.section_title, item.spec_id))


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_parsed_objects(file_id: str, base: Path) -> list[ParsedObject]:
    parsed_path = base / "parsed" / "objects.json"
    if not parsed_path.exists():
        raise FileNotFoundError("parsed_objects_missing")
    data = _load_json(parsed_path)
    return [PARSED_OBJECT_ADAPTER.validate_python(item) for item in data]


@files_router.post("/chunks/{file_id}", response_model=dict[str, list[str]])
def create_chunks(file_id: str) -> dict[str, list[str]]:
    """Compute and persist section chunks for the provided file."""

    try:
        return run_chunking(file_id)
    except FileNotFoundError as exc:
        detail = str(exc) or "Required artifacts missing."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


@files_router.get("/chunks/{file_id}", response_model=dict[str, list[str]])
def get_chunks(file_id: str) -> dict[str, list[str]]:
    """Return persisted section chunks for the provided file."""

    try:
        return load_persisted_chunks(file_id)
    except FileNotFoundError as exc:
        detail = str(exc) or "Chunks not found."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


@files_router.get("/headers/{file_id}", response_model=SectionNode)
def get_headers(file_id: str) -> SectionNode:
    """Return persisted section hierarchy for a file."""

    try:
        return load_persisted_headers(file_id)
    except FileNotFoundError:
        try:
            return run_header_discovery(file_id, None)
        except FileNotFoundError as exc:
            detail = str(exc) or "Parsed objects missing."
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


@files_router.post("/headers/{file_id}/find", response_model=SectionNode)
def discover_headers(file_id: str, llm: str | None = Query(default=None)) -> SectionNode:
    """Run header discovery for the provided file and persist the results."""

    try:
        return run_header_discovery(file_id, llm)
    except FileNotFoundError as exc:
        detail = str(exc) or "Parsed objects missing."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc


class _NullAdapter:
    def generate(self, prompt: str) -> str:  # noqa: D401 - simple deterministic stub
        return ""


def _select_specs_adapter(llm: str | None) -> _NullAdapter:
    _ = llm  # currently deterministic fallback regardless of provider
    return _NullAdapter()


@files_router.post("/specs/{file_id}/find", response_model=list[SpecItem])
def discover_specs(file_id: str, llm: str | None = Query(default=None)) -> list[SpecItem]:
    """Extract mechanical specifications for each leaf section."""

    settings = get_settings()
    base = Path(settings.ARTIFACTS_DIR) / file_id
    if not base.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    try:
        objects = _load_parsed_objects(file_id, base)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        section_root = load_persisted_headers(file_id)
    except FileNotFoundError:
        section_root = run_header_discovery(file_id, None)

    adapter = _select_specs_adapter(llm)
    try:
        return extract_specs_for_sections(file_id, section_root, objects, adapter)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@files_router.get("/specs/{file_id}", response_model=list[SpecItem])
def get_specs(file_id: str) -> list[SpecItem]:
    """Return persisted specifications for a processed file."""

    settings = get_settings()
    target = Path(settings.ARTIFACTS_DIR) / file_id / "specs" / "specs.json"
    if not target.exists():
        try:
            return discover_specs(file_id, None)
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    payload = _load_json(target)
    return [SpecItem.model_validate(item) for item in payload]


@files_router.get("/qa/{file_id}")
def qa_report(file_id: str) -> dict[str, Any]:
    """Return quality assurance metrics for the processed file."""

    settings = get_settings()
    base = Path(settings.ARTIFACTS_DIR) / file_id
    parsed_path = base / "parsed" / "objects.json"
    sections_path = base / "headers" / "sections.json"
    chunks_path = base / "chunks" / "chunks.json"
    specs_path = base / "specs" / "specs.json"

    if not parsed_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Parsed objects missing.",
        )
    if not sections_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Header sections missing.",
        )
    if not chunks_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Section chunks missing.",
        )

    parsed_objects: list[dict[str, Any]] = _load_json(parsed_path)
    section_root = SectionNode.model_validate(_load_json(sections_path))
    chunk_map_raw = _load_json(chunks_path)
    chunk_map: dict[str, list[str]] = {
        key: [str(item) for item in value]
        for key, value in chunk_map_raw.items()
    }

    specs_present = specs_path.exists()
    specs: list[SpecItem] = []
    if specs_present:
        specs_payload = _load_json(specs_path)
        specs = [SpecItem.model_validate(item) for item in specs_payload]

    leaves = list(_iter_leaves(section_root))
    leaf_ids = {leaf.section_id for leaf in leaves}
    specs_by_section: Counter[str] = Counter(spec.section_id for spec in specs)
    leaves_with_specs = sum(1 for leaf in leaves if specs_by_section.get(leaf.section_id))

    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    for spec in specs:
        if spec.spec_id in seen_ids:
            duplicate_ids.add(spec.spec_id)
        seen_ids.add(spec.spec_id)

    mismatched_specs: list[str] = []
    for spec in specs:
        expected = chunk_map.get(spec.section_id, [])
        if spec.section_id not in leaf_ids or spec.source_object_ids != expected:
            mismatched_specs.append(spec.spec_id)

    warnings: list[str] = []
    if mismatched_specs:
        joined = ", ".join(sorted(mismatched_specs))
        warnings.append(f"Source-object mismatch for spec_ids: {joined}")
    if duplicate_ids:
        joined = ", ".join(sorted(duplicate_ids))
        warnings.append(f"Duplicate spec_ids detected: {joined}")

    coverage = {
        "parsed_object_count": len(parsed_objects),
        "leaf_section_count": len(leaves),
        "specs_count": len(specs),
        "leaf_spec_ratio": (leaves_with_specs / len(leaves)) if leaves else 0.0,
    }

    consistency = {
        "source_alignment": not mismatched_specs,
        "unique_spec_ids": not duplicate_ids,
        "sections_present": True,
        "chunks_present": True,
        "specs_present": specs_present,
    }

    determinism = {
        "sections_sha256": _compute_sha256(sections_path),
        "chunks_sha256": _compute_sha256(chunks_path),
        "specs_sha256": _compute_sha256(specs_path) if specs_present else None,
    }

    return {
        "file_id": file_id,
        "qa": {
            "coverage": coverage,
            "consistency": consistency,
            "determinism": determinism,
            "warnings": warnings,
        },
    }


@files_router.get("/export/{file_id}")
def export_file(file_id: str, fmt: str = Query(default="json")) -> StreamingResponse:
    """Export sections and specs as JSON or CSV."""

    settings = get_settings()
    base = Path(settings.ARTIFACTS_DIR) / file_id
    parsed_path = base / "parsed" / "objects.json"
    sections_path = base / "headers" / "sections.json"
    chunks_path = base / "chunks" / "chunks.json"
    specs_path = base / "specs" / "specs.json"

    if not parsed_path.exists():
        if not base.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Parsed objects missing.",
        )
    if not sections_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Header sections missing.",
        )
    if not chunks_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Section chunks missing.",
        )
    if not specs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Specs not found.",
        )

    normalized = fmt.lower()
    if normalized not in {"json", "csv"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported export format.",
        )

    section_root = SectionNode.model_validate(_load_json(sections_path))
    specs_payload = [SpecItem.model_validate(item) for item in _load_json(specs_path)]
    ordered_specs = _sorted_specs(specs_payload)

    if normalized == "json":
        content = json.dumps(
            {
                "file_id": file_id,
                "sections": [section_root.model_dump(mode="json")],
                "specs": [item.model_dump(mode="json") for item in ordered_specs],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        headers = {
            "Content-Disposition": f'attachment; filename="export_{file_id}.json"'
        }
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="application/json",
            headers=headers,
        )

    header_row = [
        "spec_id",
        "file_id",
        "section_id",
        "section_number",
        "section_title",
        "spec_text",
        "confidence",
        "source_object_ids",
    ]

    def row_iter() -> Iterator[bytes]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header_row)
        yield buffer.getvalue().encode("utf-8")
        for item in ordered_specs:
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(
                [
                    item.spec_id,
                    item.file_id,
                    item.section_id,
                    item.section_number or "",
                    item.section_title,
                    item.spec_text,
                    "" if item.confidence is None else f"{item.confidence}",
                    json.dumps(item.source_object_ids, ensure_ascii=False, separators=(",", ":")),
                ]
            )
            yield buffer.getvalue().encode("utf-8")

    headers = {
        "Content-Disposition": f'attachment; filename="export_{file_id}.csv"'
    }
    return StreamingResponse(row_iter(), media_type="text/csv", headers=headers)
