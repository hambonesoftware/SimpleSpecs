"""Tests covering automatic database migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend import database
from backend.config import reset_settings_cache


def _create_legacy_document_table(path: Path) -> None:
    """Create a ``document`` table missing the ``mime_type`` column."""

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE document (
                id INTEGER PRIMARY KEY,
                filename VARCHAR NOT NULL,
                checksum VARCHAR NOT NULL,
                uploaded_at DATETIME NOT NULL,
                status VARCHAR NOT NULL
            )
            """
        )


def test_init_db_backfills_mime_type_column(tmp_path, monkeypatch):
    """``init_db`` should add the ``mime_type`` column when it is missing."""

    db_path = tmp_path / "legacy.db"
    _create_legacy_document_table(db_path)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    database.reset_database_state()
    reset_settings_cache()

    database.init_db()

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(document)")
        }

    assert "mime_type" in columns
