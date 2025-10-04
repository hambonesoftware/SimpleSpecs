"""Database utilities for SimpleSpecs."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, Session, create_engine

from .config import get_settings

_engine: Engine | None = None
_engine_url: str | None = None
_initialized: bool = False


def _ensure_sqlite_directory(database_url: str) -> dict[str, object]:
    """Return connection arguments for SQLite and ensure its directory exists."""

    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):  # pragma: no cover - simple guard
        connect_args["check_same_thread"] = False
        if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
            db_path = Path(database_url.replace("sqlite:///", "", 1)).expanduser()
            if db_path.is_absolute():
                db_dir = db_path.parent
            else:
                db_dir = Path.cwd() / db_path.parent
            db_dir.mkdir(parents=True, exist_ok=True)
    return connect_args


def get_engine() -> Engine:
    """Return the cached SQLAlchemy engine."""

    global _engine, _engine_url, _initialized
    settings = get_settings()
    database_url = settings.DB_URL
    if _engine is None or _engine_url != database_url:
        if _engine is not None:
            _engine.dispose()
        connect_args = _ensure_sqlite_directory(database_url)
        _engine = create_engine(database_url, echo=False, connect_args=connect_args)
        _engine_url = database_url
        _initialized = False
    return _engine


def init_db() -> None:
    """Create all database tables if they do not yet exist."""

    global _initialized
    engine = get_engine()
    if _initialized:
        return
    SQLModel.metadata.create_all(engine)
    _initialized = True


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""

    init_db()
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive rollback
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""

    init_db()
    with Session(get_engine()) as session:
        yield session
