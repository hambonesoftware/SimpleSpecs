# section_chunking.py
"""Helpers for constructing section chunks from located headers, with traceable decisions."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol, Sequence, runtime_checkable


@runtime_checkable
class Tracer(Protocol):
    """Minimal protocol for a tracer object.

    Any object with an ``emit(event_type: str, **data)`` method will work.
    A bare callable like ``def tracer(event, **data): ...`` is also accepted.
    """

    def emit(self, event_type: str, **data: Any) -> None:  # pragma: no cover - protocol
        ...


TraceLike = Callable[..., None] | Tracer | None


def _emit(tracer: TraceLike, event_type: str, **data: Any) -> None:
    """Fire a trace event if a tracer is provided.

    Supports either:
      • object with ``.emit(event_type, **data)``
      • callable like ``tracer(event_type, **data)``
    """
    if tracer is None:
        return
    try:
        if hasattr(tracer, "emit"):
            # type: ignore[attr-defined]
            tracer.emit(event_type, **data)
        else:
            # Assume callable
            # type: ignore[misc]
            tracer(event_type, **data)
    except TypeError:
        # Last-ditch compatibility: allow callables that only take (event_type)
        # without kwargs. This keeps older tracers from breaking.
        # type: ignore[misc]
        tracer(event_type)  # pragma: no cover - compatibility path


def _safe_int(value: object) -> int | None:
    """Return ``value`` coerced to ``int`` when possible."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def single_chunks_from_headers(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    tracer: TraceLike = None,
) -> List[Dict]:
    """Return contiguous line ranges for each header.

    Trace events (when ``tracer`` is provided):
      - chunking_start:         {headers_count, lines_count}
      - line_index_map_built:   {indexed_count, missing_global_idx}
      - header_missing_global:  {position}
      - header_not_in_lines:    {position, global_idx}
      - chunk_bounds_resolved:  {position, current_idx, end_index, next_idx, next_global}
      - chunk_skipped_inverted: {position, current_idx, end_index}
      - chunk_built:            {position, header_text, header_number, level,
                                 start_global_idx, end_global_idx,
                                 start_page, end_page, line_count}
      - chunking_complete:      {chunks_count}
    """

    if not headers:
        _emit(tracer, "chunking_start", headers_count=0, lines_count=len(lines))
        _emit(tracer, "chunking_complete", chunks_count=0)
        return []

    _emit(tracer, "chunking_start", headers_count=len(headers), lines_count=len(lines))

    # Build a fast lookup: global_idx -> line index
    index_by_global: Dict[int, int] = {}
    missing_in_lines = 0
    for idx, line in enumerate(lines):
        global_idx = _safe_int(line.get("global_idx"))
        if global_idx is None:
            missing_in_lines += 1
            continue
        # If duplicates somehow exist, keep the first occurrence (stable)
        index_by_global.setdefault(global_idx, idx)

    _emit(
        tracer,
        "line_index_map_built",
        indexed_count=len(index_by_global),
        missing_global_idx=missing_in_lines,
    )

    chunks: list[Dict] = []

    for position, header in enumerate(headers):
        current_global = _safe_int(header.get("global_idx"))
        if current_global is None:
            _emit(tracer, "header_missing_global", position=position)
            continue

        current_idx = index_by_global.get(current_global)
        if current_idx is None:
            _emit(
                tracer,
                "header_not_in_lines",
                position=position,
                global_idx=current_global,
            )
            continue

        # Determine the end index (up to the line before the next header's line)
        if position < len(headers) - 1:
            next_header = headers[position + 1]
            next_global = _safe_int(next_header.get("global_idx"))
            if next_global is None:
                next_idx = len(lines)
            else:
                next_idx = index_by_global.get(next_global, len(lines))
            end_index = max(current_idx, next_idx - 1)
        else:
            next_global = None
            next_idx = None
            end_index = len(lines) - 1

        _emit(
            tracer,
            "chunk_bounds_resolved",
            position=position,
            current_idx=current_idx,
            end_index=end_index,
            next_idx=next_idx,
            next_global=next_global,
        )

        # Guard: inverted bounds (should be rare but can happen if next header
        # maps earlier than current due to parsing anomalies). Skip such ranges.
        if end_index < current_idx:
            _emit(
                tracer,
                "chunk_skipped_inverted",
                position=position,
                current_idx=current_idx,
                end_index=end_index,
            )
            continue

        # Build the chunk using the resolved indices
        start_line = lines[current_idx]
        end_line = lines[end_index]
        level = int(header.get("level") or 1)

        chunk = {
            "header_text": header.get("text"),
            "header_number": header.get("number"),
            "level": level,
            "start_global_idx": int(start_line.get("global_idx", 0)),
            "end_global_idx": int(end_line.get("global_idx", 0)),
            "start_page": int(start_line.get("page", 0)),
            "end_page": int(end_line.get("page", 0)),
        }
        chunks.append(chunk)

        _emit(
            tracer,
            "chunk_built",
            position=position,
            header_text=(chunk["header_text"] or "")[:200],  # keep traces small
            header_number=chunk.get("header_number"),
            level=level,
            start_global_idx=chunk["start_global_idx"],
            end_global_idx=chunk["end_global_idx"],
            start_page=chunk["start_page"],
            end_page=chunk["end_page"],
            line_count=(end_index - current_idx + 1),
        )

    _emit(tracer, "chunking_complete", chunks_count=len(chunks))
    return chunks


__all__ = ["single_chunks_from_headers", "Tracer", "TraceLike"]
