"""Utility helpers for storing intermediate parsing and extraction results."""
from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Mapping, Sequence, Set as AbstractSet
from pathlib import Path
from typing import Any, Iterable, Iterator


_TMP_DIR = Path(tempfile.gettempdir()) / "simplespecs"
_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _path_for(name: str) -> Path:
    return _TMP_DIR / name


def upload_objects_path(upload_id: str) -> Path:
    """Return the JSONL path for the parsed objects of an upload."""

    return _path_for(f"{upload_id}.jsonl")


def headers_path(upload_id: str) -> Path:
    return _path_for(f"{upload_id}_headers.json")


def specs_path(upload_id: str) -> Path:
    return _path_for(f"{upload_id}_specs.json")


def _normalize_json(value: Any) -> Any:
    """Convert *value* into a JSON-serializable structure."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(val) for key, val in value.items()}
    if isinstance(value, AbstractSet):
        return [_normalize_json(val) for val in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(val) for val in value]
    return str(value)


def write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(_normalize_json(item), ensure_ascii=False))
            fh.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_normalize_json(payload), fh, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_csv(path: Path, rows: Iterable[Iterable[Any]], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow(list(row))


def stream_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
