"""Helpers for constructing section chunks from located headers."""

from __future__ import annotations

from typing import Dict, List, Sequence


def _safe_int(value: object) -> int | None:
    """Return ``value`` coerced to ``int`` when possible."""

    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def single_chunks_from_headers(
    headers: Sequence[Dict], lines: Sequence[Dict]
) -> List[Dict]:
    """Return contiguous line ranges for each header."""

    if not headers:
        return []

    index_by_global: Dict[int, int] = {}
    for idx, line in enumerate(lines):
        global_idx = _safe_int(line.get("global_idx"))
        if global_idx is None:
            continue
        index_by_global.setdefault(global_idx, idx)
    chunks: list[Dict] = []

    for position, header in enumerate(headers):
        current_global = _safe_int(header.get("global_idx"))
        if current_global is None:
            continue

        current_idx = index_by_global.get(current_global)
        if current_idx is None:
            continue
        if position < len(headers) - 1:
            next_header = headers[position + 1]
            next_global = _safe_int(next_header.get("global_idx"))
            if next_global is None:
                next_idx = len(lines)
            else:
                next_idx = index_by_global.get(next_global, len(lines))
            end_index = max(current_idx, next_idx - 1)
        else:
            end_index = len(lines) - 1

        if end_index < current_idx:
            continue

        start_line = lines[current_idx]
        end_line = lines[end_index]
        chunks.append(
            {
                "header_text": header.get("text"),
                "header_number": header.get("number"),
                "level": int(header.get("level") or 1),
                "start_global_idx": int(start_line.get("global_idx", 0)),
                "end_global_idx": int(end_line.get("global_idx", 0)),
                "start_page": int(start_line.get("page", 0)),
                "end_page": int(end_line.get("page", 0)),
            }
        )

    return chunks


__all__ = ["single_chunks_from_headers"]
