"""Database utilities for the SimpleSpecs backend."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import NoSuchTableError
from sqlmodel import Session, SQLModel, create_engine

from . import config as config_module
from .config import PROJECT_ROOT
from .migrations import run_migrations

_engine = None


def get_engine():
    """Return a SQLModel engine using configured settings."""

    global _engine
    if _engine is None:
        settings = config_module.get_settings()
        database_url = settings.database_url
        url = make_url(database_url)
        connect_args = {"check_same_thread": False} if url.get_backend_name() == "sqlite" else {}

        if url.get_backend_name() == "sqlite":
            database = url.database
            if database and database != ":memory:":
                db_path = Path(database)
                if not db_path.is_absolute():
                    db_path = (PROJECT_ROOT / db_path).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                url = url.set(database=str(db_path))
                database_url = url.render_as_string(hide_password=False)

        _engine = create_engine(database_url, connect_args=connect_args)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Provide a SQLModel session for FastAPI dependencies."""

    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Initialise database tables."""

    from .models import (  # noqa: F401  Ensures models are registered with SQLModel metadata.
        artifacts,
        document,
        header_anchor,
        section,
        spec_record,
    )

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    run_migrations(engine)

    # Ensure critical migrations have been applied even if the database
    # started in an unexpected state (e.g., tests overriding ``DATABASE_URL``
    # mid-session).
    with engine.begin() as connection:
        inspector = inspect(connection)
        try:
            columns = inspector.get_columns("document")
        except NoSuchTableError:
            return

        if not any(column["name"] == "mime_type" for column in columns):
            connection.execute(text("ALTER TABLE document ADD COLUMN mime_type VARCHAR"))


def reset_database_state() -> None:
    """Reset the cached engine (useful for tests)."""

    global _engine
    _engine = None
