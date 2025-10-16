"""CLI entrypoint for indexing specification chunks."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Sequence

from ..config import Settings, get_settings
from ..models import PARSED_OBJECT_ADAPTER, PARSED_OBJECT_TYPES, ParsedObject, SpecItem
from ..services.chunker import run_chunking
from ..services.headers import run_header_discovery
from ..services.pdf_parser import MinerUUnavailableError, select_pdf_parser
from ..services.spec_rag import extract_specs, index_specs, load_spec_items


def _determine_file_id(source: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    path = Path(source)
    if path.is_file():
        return path.stem
    return source


def _stage_source(file_id: str, source: Path, settings: Settings) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"source_missing:{source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError("Only PDF sources are supported for spec indexing")
    target_dir = Path(settings.ARTIFACTS_DIR) / file_id / "source"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "document.pdf"
    shutil.copy2(source, target)
    return target


def _locate_document(file_id: str, settings: Settings) -> Path | None:
    candidate = Path(settings.ARTIFACTS_DIR) / file_id / "source" / "document.pdf"
    return candidate if candidate.exists() else None


def _ordered_objects(file_id: str, objects: Iterable[ParsedObject]) -> list[ParsedObject]:
    ordered: list[ParsedObject] = []
    for idx, obj in enumerate(objects):
        if not isinstance(obj, PARSED_OBJECT_TYPES):
            obj = PARSED_OBJECT_ADAPTER.validate_python(obj)
        updates = {
            "file_id": file_id,
            "order_index": idx,
        }
        if not getattr(obj, "object_id", None):
            updates["object_id"] = f"{file_id}-{idx:06d}"
        ordered.append(obj.model_copy(update=updates))
    return ordered


def _write_objects(file_id: str, objects: Sequence[ParsedObject], settings: Settings) -> Path:
    target = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [obj.model_dump(mode="json") for obj in objects]
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return target


def _parse_pdf(file_id: str, pdf_path: Path, settings: Settings) -> list[ParsedObject]:
    parser = select_pdf_parser(settings=settings, file_path=str(pdf_path))
    try:
        objects = parser.parse_pdf(str(pdf_path))
    except MinerUUnavailableError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("mineru_not_available") from exc
    except RuntimeError as exc:
        raise RuntimeError(f"pdf_parse_failed:{exc}") from exc
    return _ordered_objects(file_id, objects)


def _ensure_pipeline(
    file_id: str,
    *,
    pdf_path: Path | None,
    settings: Settings,
    rebuild: bool,
) -> None:
    parsed_path = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    sections_path = Path(settings.ARTIFACTS_DIR) / file_id / "headers" / "sections.json"
    chunks_path = Path(settings.ARTIFACTS_DIR) / file_id / "chunks" / "chunks.json"

    def require_pdf() -> Path:
        if pdf_path is None:
            existing = _locate_document(file_id, settings)
            if existing is None:
                raise FileNotFoundError("source_document_missing")
            return existing
        return pdf_path

    needs_parse = rebuild or not parsed_path.exists()
    needs_headers = rebuild or not sections_path.exists()
    needs_chunks = rebuild or not chunks_path.exists()

    if needs_parse:
        path = require_pdf()
        objects = _parse_pdf(file_id, path, settings)
        _write_objects(file_id, objects, settings)
    if needs_headers:
        require_pdf()  # ensure error if pdf missing
        run_header_discovery(file_id, llm_choice=None)
    if needs_chunks:
        run_chunking(file_id, settings=settings)


def _extract_or_load_specs(file_id: str, settings: Settings) -> list[SpecItem]:
    try:
        return load_spec_items(file_id, settings=settings)
    except FileNotFoundError:
        specs = extract_specs(file_id, settings=settings, persist=True)
        return specs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index specification chunks for hybrid search")
    parser.add_argument("source", help="File identifier or source document path")
    parser.add_argument("--file-id", help="Explicit file identifier override")
    parser.add_argument("--rebuild", action="store_true", help="Re-run parsing and extraction")
    args = parser.parse_args(argv)

    settings = get_settings()
    file_id = _determine_file_id(args.source, args.file_id)
    source_path = Path(args.source)
    staged_pdf: Path | None = None

    if source_path.is_file():
        try:
            staged_pdf = _stage_source(file_id, source_path, settings)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error staging source: {exc}", file=sys.stderr)
            return 1
    elif args.rebuild:
        staged_pdf = _locate_document(file_id, settings)
        if staged_pdf is None:
            print("Rebuild requested but no staged PDF found. Provide a source path.", file=sys.stderr)
            return 1

    try:
        _ensure_pipeline(file_id, pdf_path=staged_pdf, settings=settings, rebuild=args.rebuild)
        specs = _extract_or_load_specs(file_id, settings)
        index_specs(file_id, settings=settings, specs=specs)
    except FileNotFoundError as exc:
        code = exc.args[0] if exc.args else "missing_artifacts"
        print(f"Required artifact missing ({code}). Provide --rebuild with a PDF source.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Failed to parse document: {exc}", file=sys.stderr)
        return 1

    print(f"Indexed {len(specs)} specifications for '{file_id}'.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
