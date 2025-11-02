"""Utilities for accessing parsed document lines with reliable line numbers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, TypedDict

from sqlmodel import select

from .. import config as config_module
from .. import models as models_pkg


class Line(TypedDict):
    page: int           # 1-based page index
    line_in_page: int   # 1-based line index within the page
    text: str


def _coerce_line(
    page_value,
    line_in_page_value,
    text_value,
    counters: Dict[int, int],
) -> Line:
    try:
        page = int(page_value)
    except (TypeError, ValueError):
        page = 1
    if page <= 0:
        page = 1

    text = str(text_value or "")

    try:
        line_number = int(line_in_page_value)
    except (TypeError, ValueError):
        counters[page] = counters.get(page, 0) + 1
        line_number = counters[page]
    else:
        if line_number <= 0:
            counters[page] = counters.get(page, 0) + 1
            line_number = counters[page]
        else:
            counters[page] = max(counters.get(page, 0), line_number)

    return Line(page=page, line_in_page=line_number, text=text)


def _iter_lines_jsonl(jsonl_path: Path) -> Iterator[Line]:
    if not jsonl_path.exists():
        return iter(())

    counters: Dict[int, int] = {}
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            page = payload.get("page", 1)
            line_in_page = payload.get("line_in_page")
            text = payload.get("text", "")
            yield _coerce_line(page, line_in_page, text, counters)


def _iter_db_lines(session, document_id: int) -> Iterator[Line]:
    model = getattr(models_pkg, "DocumentLine", None)
    if model is None or session is None:
        return iter(())

    try:
        statement = (
            select(model)
            .where(model.document_id == document_id)
            .order_by(
                getattr(model, "page", getattr(model, "page_index", 0)),
                getattr(model, "line_in_page", getattr(model, "line", 0)),
            )
        )
        rows = session.exec(statement).all()
    except Exception:
        return iter(())

    if not rows:
        return iter(())

    counters: Dict[int, int] = {}
    for row in rows:
        page = getattr(row, "page", None)
        if page is None:
            page = getattr(row, "page_index", 1)
        line_in_page = getattr(row, "line_in_page", None)
        if line_in_page is None:
            line_in_page = getattr(row, "line", None)
        text = getattr(row, "text", "")
        yield _coerce_line(page, line_in_page, text, counters)


def _iter_page_layout_lines(session, document_id: int) -> Iterator[Line]:
    model = getattr(models_pkg, "DocumentPage", None)
    if model is None or session is None:
        return iter(())

    try:
        statement = (
            select(model)
            .where(model.document_id == document_id)
            .order_by(getattr(model, "page", getattr(model, "page_index", 0)))
        )
        rows = session.exec(statement).all()
    except Exception:
        return iter(())

    if not rows:
        return iter(())

    counters: Dict[int, int] = {}
    for row in rows:
        page = getattr(row, "page", None)
        if page is None:
            page = getattr(row, "page_index", 1)

        layout = getattr(row, "layout", None)
        emitted = False
        if isinstance(layout, list) and layout:
            for block in layout:
                text_value = block.get("text") if isinstance(block, dict) else None
                if not isinstance(text_value, str):
                    continue
                for piece in text_value.splitlines() or [text_value]:
                    cleaned = piece.strip()
                    if not cleaned:
                        continue
                    emitted = True
                    yield _coerce_line(page, None, cleaned, counters)
        text_raw = getattr(row, "text_raw", "")
        if not emitted and isinstance(text_raw, str):
            for piece in text_raw.splitlines() or [text_raw]:
                cleaned = piece.strip()
                if not cleaned:
                    continue
                yield _coerce_line(page, None, cleaned, counters)


def iter_lines(session, document_id: int) -> Iterable[Line]:
    db_lines = list(_iter_db_lines(session, document_id))
    if db_lines:
        return db_lines

    page_layout_lines = list(_iter_page_layout_lines(session, document_id))
    if page_layout_lines:
        return page_layout_lines

    settings = config_module.get_settings()
    candidates: List[Path] = []
    if settings is not None:
        candidates.append(settings.export_dir / str(document_id) / "lines.jsonl")
    candidates.append(Path(f"exports/{document_id}/lines.jsonl"))

    for path in candidates:
        lines = list(_iter_lines_jsonl(path))
        if lines:
            return lines

    return []


def get_fulltext(session, document_id: int) -> str:
    return "\n".join(line["text"] for line in iter_lines(session, document_id))


__all__ = ["Line", "iter_lines", "get_fulltext"]
