#!/usr/bin/env python3
"""Replay header extraction for SimpleSpecs artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.routers._headers_common import (
    clean_document_for_headers,
    parse_and_store_headers,
    rule_based_headers,
)
from backend.services.pdf_parser import select_pdf_parser
from backend.services.text_blocks import document_line_entries, document_text

DEFAULT_INDEX = ROOT / "tests" / "golden" / "before" / "index.json"
LOGGER = logging.getLogger("run_headers")


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "-", name.strip().lower())
    return slug.strip("-")


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_artifact_pdf(source: Path, upload_id: str, *, settings) -> Path:
    base = Path(settings.ARTIFACTS_DIR) / upload_id
    source_dir = base / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    destination = source_dir / source.name
    if not destination.exists() or _hash_file(destination) != _hash_file(source):
        shutil.copy2(source, destination)
    return destination


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _load_objects(parsed_path: Path) -> list[dict]:
    with parsed_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _store_objects(parsed_path: Path, objects: Sequence[dict]) -> None:
    _write_json(parsed_path, list(objects))


def _format_response_block(items: Sequence[dict]) -> str:
    lines = []
    for entry in items:
        number = str(entry.get("section_number", "")).strip()
        name = str(entry.get("section_name", "")).strip()
        if number and name:
            lines.append(f"{number} {name}")
        elif name:
            lines.append(name)
    body = "\n".join(lines)
    return f"#headers#\n{body}\n#headers#"


def _objects_to_lines(objects: Sequence[dict]) -> list[dict]:
    entries = []
    for entry in document_line_entries(objects):
        entries.append(
            {
                "text": entry.text,
                "page_index": entry.page_index,
                "line_index": entry.line_index,
            }
        )
    return entries


def _run_pipeline_for_pdf(
    pdf_path: Path, *, engine: str = "native"
) -> tuple[str, list[dict], list[dict], list[dict], str]:
    settings = get_settings()
    upload_id = _hash_file(pdf_path)
    stored_pdf = _ensure_artifact_pdf(pdf_path, upload_id, settings=settings)
    parsed_path = stored_pdf.parent.parent / "parsed" / "objects.json"

    if parsed_path.exists():
        objects = _load_objects(parsed_path)
    else:
        parser = select_pdf_parser(settings=settings, file_path=str(stored_pdf), override=engine)
        parsed_objects = parser.parse_pdf(str(stored_pdf))
        objects = [obj.model_dump(mode="json") for obj in parsed_objects]
        _store_objects(parsed_path, objects)

    lines = _objects_to_lines(objects)
    document = document_text(objects)
    cleaned = clean_document_for_headers(document)
    seed_headers = rule_based_headers(cleaned) or rule_based_headers(document)
    response_payload = [item.model_dump() for item in seed_headers]
    response_text = _format_response_block(response_payload)

    headers = parse_and_store_headers(
        upload_id,
        response_text,
        cleaned_document=cleaned,
    )
    header_items = [header.model_dump() for header in headers]

    return upload_id, objects, header_items, lines, response_text


def _find_pdf_for_upload(
    upload_id: str,
    *,
    settings,
    index_path: Path | None = None,
) -> Path:
    """Return a PDF path for a stored upload."""

    source_dir = Path(settings.ARTIFACTS_DIR) / upload_id / "source"
    if source_dir.exists():
        for candidate in sorted(p for p in source_dir.iterdir() if p.is_file()):
            return candidate

    if index_path is not None and index_path.exists():
        try:
            with index_path.open("r", encoding="utf-8") as handle:
                entries = json.load(handle)
        except json.JSONDecodeError as exc:  # pragma: no cover - configuration error
            raise RuntimeError(f"Invalid index JSON: {index_path}") from exc

        for entry in entries:
            if entry.get("upload_id") == upload_id and entry.get("pdf"):
                candidate = ROOT / entry["pdf"]
                if candidate.exists():
                    return candidate

    raise FileNotFoundError(f"No stored PDF found for upload_id={upload_id}")


def _diff(actual: object, expected: object) -> tuple[bool, str]:
    actual_text = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
    expected_text = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)
    if actual_text == expected_text:
        return True, ""

    import difflib

    diff = difflib.unified_diff(
        expected_text.splitlines(),
        actual_text.splitlines(),
        fromfile="expected",
        tofile="actual",
        lineterm="",
    )
    return False, "\n".join(diff)


def record_baseline(
    pdf_path: Path | None = None,
    *,
    index_path: Path = DEFAULT_INDEX,
    engine: str = "native",
    upload_id: str | None = None,
) -> None:
    settings = get_settings()

    resolved_pdf: Path | None = None
    if pdf_path is not None:
        resolved_pdf = pdf_path.resolve()
        if not resolved_pdf.exists():
            raise FileNotFoundError(f"PDF not found: {resolved_pdf}")

    if resolved_pdf is None:
        if upload_id is None:
            raise ValueError("Either pdf_path or upload_id must be provided")
        resolved_pdf = _find_pdf_for_upload(upload_id, settings=settings, index_path=index_path)

    if upload_id is not None and resolved_pdf is not None:
        actual_upload = _hash_file(resolved_pdf)
        if actual_upload != upload_id:
            raise ValueError(
                f"Provided upload_id ({upload_id}) does not match PDF hash {actual_upload}",
            )

    upload_id_result, objects, header_items, lines, response_text = _run_pipeline_for_pdf(
        resolved_pdf, engine=engine
    )
    stem = _slugify(resolved_pdf.stem)

    golden_dir = index_path.parent
    layout_dir = ROOT / "tests" / "fixtures" / "layout"

    parsed_file = golden_dir / f"{stem}.objects.json"
    headers_file = golden_dir / f"{stem}.headers.json"
    raw_file = golden_dir / f"{stem}.headers.raw.txt"
    layout_file = layout_dir / f"{stem}.lines.jsonl"

    _write_json(parsed_file, objects)
    _write_json(headers_file, header_items)
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(response_text, encoding="utf-8")
    layout_file.parent.mkdir(parents=True, exist_ok=True)
    with layout_file.open("w", encoding="utf-8") as handle:
        for entry in lines:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    index: list[dict]
    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as handle:
            index = json.load(handle)
    else:
        index = []

    entry = {
        "name": stem,
        "pdf": str(resolved_pdf.relative_to(ROOT)),
        "upload_id": upload_id_result,
        "parsed": str(parsed_file.relative_to(ROOT)),
        "headers": str(headers_file.relative_to(ROOT)),
        "raw": str(raw_file.relative_to(ROOT)),
        "layout": str(layout_file.relative_to(ROOT)),
    }

    index = [item for item in index if item.get("name") != stem]
    index.append(entry)
    index.sort(key=lambda item: item["name"])
    _write_json(index_path, index)
    LOGGER.info("Recorded baseline for %s (upload_id=%s)", resolved_pdf.name, upload_id_result)


def check_baselines(
    index_path: Path = DEFAULT_INDEX,
    *,
    engine: str = "native",
    upload_id: str | None = None,
) -> int:
    if not index_path.exists():
        LOGGER.error("Missing index file: %s", index_path)
        return 1

    with index_path.open("r", encoding="utf-8") as handle:
        entries = json.load(handle)

    if upload_id is not None:
        entries = [entry for entry in entries if entry.get("upload_id") == upload_id]
        if not entries:
            LOGGER.error("No baseline entries match upload_id=%s", upload_id)
            return 1

    failures: list[str] = []
    for entry in entries:
        pdf_path = ROOT / entry["pdf"]
        upload_id, objects, header_items, lines, response_text = _run_pipeline_for_pdf(
            pdf_path, engine=engine
        )

        parsed_file = ROOT / entry["parsed"]
        headers_file = ROOT / entry["headers"]
        raw_file = ROOT / entry["raw"]
        layout_file = ROOT / entry["layout"]

        expected_objects = json.loads(parsed_file.read_text(encoding="utf-8"))
        expected_headers = json.loads(headers_file.read_text(encoding="utf-8"))
        expected_raw = raw_file.read_text(encoding="utf-8")
        expected_lines = [
            json.loads(line)
            for line in layout_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        ok_objects, diff_objects = _diff(objects, expected_objects)
        ok_headers, diff_headers = _diff(header_items, expected_headers)
        ok_raw = response_text.strip() == expected_raw.strip()
        ok_lines, diff_lines = _diff(lines, expected_lines)

        if not (ok_objects and ok_headers and ok_raw and ok_lines):
            details = [f"upload_id={upload_id}"]
            if not ok_objects:
                details.append(f"parsed diff:\n{diff_objects}")
            if not ok_headers:
                details.append(f"headers diff:\n{diff_headers}")
            if not ok_raw:
                details.append("raw header block mismatch")
            if not ok_lines:
                details.append(f"layout diff:\n{diff_lines}")
            failures.append(f"{entry['name']}:\n" + "\n".join(details))

    if failures:
        for failure in failures:
            LOGGER.error("%s", failure)
        return 1
    LOGGER.info("All baselines match (%d)", len(entries))
    return 0


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices={"record", "check"}, help="Action to perform")
    parser.add_argument("target", nargs="?", help="Path to PDF when recording")
    parser.add_argument("--index", dest="index", default=str(DEFAULT_INDEX), help="Path to baseline index JSON")
    parser.add_argument("--engine", dest="engine", default="native", help="PDF engine override")
    parser.add_argument(
        "--upload-id",
        dest="upload_id",
        help="Replay using an existing upload_id",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = parse_args(argv or sys.argv[1:])
    index_path = Path(args.index).resolve()

    if args.command == "record":
        pdf_path = Path(args.target).resolve() if args.target else None
        try:
            record_baseline(
                pdf_path,
                index_path=index_path,
                engine=args.engine,
                upload_id=args.upload_id,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        return 0

    if args.command == "check":
        return check_baselines(
            index_path=index_path,
            engine=args.engine,
            upload_id=args.upload_id,
        )

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
