"""Database utilities for the SimpleSpecs backend."""
from __future__ import annotations

from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine = None


def get_engine():
    """Return a SQLModel engine using configured settings."""

    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, connect_args=connect_args)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Provide a SQLModel session for FastAPI dependencies."""

    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Initialise database tables."""

    from .models import (  # noqa: F401  Ensures models are registered with SQLModel metadata.
        document,
        spec_record,
    )

    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def reset_database_state() -> None:
    """Reset the cached engine (useful for tests)."""

    global _engine
    _engine = None
