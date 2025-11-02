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


def _ensure_document_byte_size(engine: Engine) -> None:
    """Add the ``byte_size`` column to ``document`` when absent."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "byte_size" for column in columns):
            return

        connection.execute(
            text("ALTER TABLE document ADD COLUMN byte_size INTEGER NOT NULL DEFAULT 0")
        )


def _ensure_document_page_count(engine: Engine) -> None:
    """Add the ``page_count`` column to ``document`` when missing."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "page_count" for column in columns):
            return

        connection.execute(
            text("ALTER TABLE document ADD COLUMN page_count INTEGER")
        )


def _ensure_document_has_ocr(engine: Engine) -> None:
    """Add the ``has_ocr`` flag to ``document`` when missing."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "has_ocr" for column in columns):
            return

        connection.execute(
            text("ALTER TABLE document ADD COLUMN has_ocr BOOLEAN NOT NULL DEFAULT 0")
        )


def _ensure_document_used_mineru(engine: Engine) -> None:
    """Add the ``used_mineru`` flag to ``document`` when missing."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "used_mineru" for column in columns):
            return

        connection.execute(
            text(
                "ALTER TABLE document ADD COLUMN used_mineru BOOLEAN NOT NULL DEFAULT 0"
            )
        )


def _ensure_document_parser_version(engine: Engine) -> None:
    """Ensure the ``parser_version`` column exists on ``document``."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "parser_version" for column in columns):
            return

        connection.execute(
            text("ALTER TABLE document ADD COLUMN parser_version VARCHAR")
        )


def _ensure_document_last_parsed_at(engine: Engine) -> None:
    """Ensure the ``last_parsed_at`` column exists on ``document``."""

    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if any(column["name"] == "last_parsed_at" for column in columns):
            return

        connection.execute(
            text("ALTER TABLE document ADD COLUMN last_parsed_at DATETIME")
        )


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
    _ensure_document_byte_size,
    _ensure_document_page_count,
    _ensure_document_has_ocr,
    _ensure_document_used_mineru,
    _ensure_document_parser_version,
    _ensure_document_last_parsed_at,
    _ensure_document_page_is_toc,
)


def run_migrations(engine: Engine, migrations: Iterable[MigrationFunc] | None = None) -> None:
    """Execute idempotent schema migrations for the provided engine."""

    for migration in migrations or _MIGRATIONS:
        migration(engine)
