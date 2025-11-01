"""Lightweight schema migration helpers for the SimpleSpecs backend."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoSuchTableError


MigrationFunc = Callable[[Engine], None]


def _ensure_document_mime_type(engine: Engine) -> None:
    """Add the ``mime_type`` column to ``document`` if it is missing."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "mime_type" for column in columns):
            return

        connection.execute(text("ALTER TABLE document ADD COLUMN mime_type VARCHAR"))


def _ensure_document_page_is_toc(engine: Engine) -> None:
    """Add the ``is_toc`` flag to ``document_pages`` when absent."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document_pages")
        except NoSuchTableError:
            return

        if any(column["name"] == "is_toc" for column in columns):
            return

        connection.execute(
            text(
                "ALTER TABLE document_pages "
                "ADD COLUMN is_toc BOOLEAN NOT NULL DEFAULT 0"
            )
        )


_MIGRATIONS: tuple[MigrationFunc, ...] = (
    _ensure_document_mime_type,
    _ensure_document_page_is_toc,
)


def run_migrations(engine: Engine, migrations: Iterable[MigrationFunc] | None = None) -> None:
    """Execute idempotent schema migrations for the provided engine."""

    for migration in migrations or _MIGRATIONS:
        migration(engine)
