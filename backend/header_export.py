from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .models import HeaderItem

_REPORT_HEADER = [
    "Header array number",
    "header array string",
    "found match string",
    "found match page",
    "found match line",
]


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return Path.cwd()


def _format_field(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())


def write_header_search_report(headers: Iterable[HeaderItem]) -> Path | None:
    items: Sequence[HeaderItem] = [item for item in headers if item is not None]
    if not items:
        return None
    root = _project_root()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = root / f"headersearch_{timestamp}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(_REPORT_HEADER) + "\n")
        for item in items:
            row = [
                _format_field(item.section_number),
                _format_field(item.section_name),
                _format_field(item.chunk_text),
                _format_field(item.page_number),
                _format_field(item.line_number),
            ]
            handle.write("\t".join(row) + "\n")
    return path


__all__ = ["write_header_search_report"]
