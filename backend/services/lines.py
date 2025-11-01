"""Utilities for working with parsed document line metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, TypedDict

from fastapi import HTTPException, status
from sqlmodel import select

from .. import models as models_pkg
from ..config import get_settings


class Line(TypedDict):
    """Typed representation of a parsed line of text."""

    page: int
    line_in_page: int
    text: str


def _iter_jsonl_lines(path: Path) -> Iterator[Line]:
    """Yield line records from a JSONL export file."""

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            chunk = raw_line.strip()
            if not chunk:
                continue
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError as exc:  # pragma: no cover - corrupted export
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Invalid line export entry",
                ) from exc

            try:
                page = int(payload["page"])
                line_in_page = int(payload["line_in_page"])
                text = str(payload.get("text", ""))
            except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - corrupted export
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Malformed line metadata",
                ) from exc

            yield Line(page=page, line_in_page=line_in_page, text=text)


def _iter_db_lines(session, document_id: int) -> Iterator[Line]:
    """Yield lines from a database model when available."""

    document_line_model = getattr(models_pkg, "DocumentLine", None)
    if document_line_model is None or session is None:
        return iter(())

    try:
        statement = (
            select(document_line_model)
            .where(document_line_model.document_id == document_id)
            .order_by(
                getattr(document_line_model, "page", 0),
                getattr(document_line_model, "line_in_page", 0),
            )
        )
        rows = session.exec(statement).all()
    except Exception:  # pragma: no cover - optional table not present
        return iter(())

    if not rows:
        return iter(())

    def _generator() -> Iterator[Line]:
        for row in rows:
            page = getattr(row, "page", None)
            if page is None:
                page = getattr(row, "page_index", 0)
            line_in_page = getattr(row, "line_in_page", None)
            if line_in_page is None:
                line_in_page = getattr(row, "line", 0)
            text = getattr(row, "text", "")
            yield Line(page=int(page), line_in_page=int(line_in_page), text=str(text))

    return _generator()


def iter_lines(session, document_id: int) -> Iterable[Line]:
    """Return the parsed lines for ``document_id``."""

    db_lines = list(_iter_db_lines(session, document_id))
    if db_lines:
        return db_lines

    settings = get_settings()
    export_path = settings.export_dir / str(document_id) / "lines.jsonl"
    if export_path.exists():
        return list(_iter_jsonl_lines(export_path))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Parsed lines not found for document",
    )


def get_fulltext(session, document_id: int) -> str:
    """Return the full document text reconstructed from parsed lines."""

    lines = iter_lines(session, document_id)
    return "\n".join(str(line["text"]) for line in lines)


__all__ = ["Line", "iter_lines", "get_fulltext"]
