"""Utilities for generating strict header alignment reports."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .headers_llm_strict import align_headers_llm_strict
from .pdf_native import parse_pdf_to_lines


def _prepare_lines(lines: list[dict]) -> list[dict]:
    for idx, line in enumerate(lines):
        line.setdefault("line_idx", idx)
        line.setdefault("global_idx", idx)
    return lines


def _header_key(header: Mapping[str, object]) -> tuple[str, str | None, int]:
    text = str(header.get("text", ""))
    number = header.get("number")
    if isinstance(number, str):
        number = number or None
    elif number is None:
        number = None
    else:
        number = str(number) or None
    level = int(header.get("level", 1) or 1)
    return text.strip(), number, level


def generate_header_alignment_report(
    pdf_path: Path,
    golden_headers: Sequence[Mapping[str, object]],
) -> list[dict]:
    """Return alignment details for *golden_headers* within *pdf_path*."""

    lines = parse_pdf_to_lines(pdf_path)
    prepared_lines = _prepare_lines(list(lines))

    resolved = align_headers_llm_strict(golden_headers, prepared_lines, tracer=None)
    resolved_map: dict[tuple[str, str | None, int], dict] = {}
    for item in resolved:
        key = _header_key(item["header"])
        resolved_map[key] = item

    report: list[dict] = []
    for header in golden_headers:
        text, number, level = _header_key(header)
        resolved_item = resolved_map.get((text, number, level))
        if resolved_item:
            line = resolved_item["line"]
            report.append(
                {
                    "text": text,
                    "number": number,
                    "level": level,
                    "page": int(line.get("page", 0)),
                    "global_index": int(line.get("global_idx", 0)),
                    "line_index": int(line.get("line_idx", 0)),
                    "line_text": str(line.get("text", "")).strip(),
                    "score": resolved_item.get("score"),
                    "strategy": resolved_item.get("strategy"),
                    "band": bool(resolved_item.get("band")),
                    "found": True,
                }
            )
        else:
            report.append(
                {
                    "text": text,
                    "number": number,
                    "level": level,
                    "page": None,
                    "global_index": None,
                    "line_index": None,
                    "line_text": None,
                    "score": None,
                    "strategy": None,
                    "band": None,
                    "found": False,
                }
            )

    return report


__all__ = ["generate_header_alignment_report"]
