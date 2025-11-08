"""Database utilities and public entry points for the spec extraction package."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy.engine import URL, make_url
from sqlmodel import Session, SQLModel, create_engine, select

from backend.config import PROJECT_ROOT, get_settings

from .models import Agent

_ENGINE = None


def _resolve_database_url(raw_url: str) -> tuple[str, dict[str, object]]:
    """Return a normalised database URL and connection arguments."""

    url: URL = make_url(raw_url)
    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        database = url.database
        if database and database not in {":memory:"}:
            db_path = Path(database)
            if not db_path.is_absolute():
                db_path = (PROJECT_ROOT / db_path).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(db_path))
    return url.render_as_string(hide_password=False), connect_args


def get_engine():
    """Return the SQLModel engine for the specs database."""

    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        database_url, connect_args = _resolve_database_url(settings.specs_db_url)
        _ENGINE = create_engine(database_url, connect_args=connect_args)
    return _ENGINE


def get_session() -> Generator[Session, None, None]:
    """Yield a session bound to the specs database."""

    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create tables and seed static data for the specs database."""

    from . import models  # noqa: F401  Ensure SQLModel metadata is populated.

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_agents(session)


def _seed_agents(session: Session) -> None:
    """Ensure the five built-in agent descriptors exist."""

    existing = set(session.exec(select(Agent.code)))
    required = {
        "Mechanical": "Mechanical discipline specialist",
        "Electrical": "Electrical discipline specialist",
        "Controls": "Controls and automation specialist",
        "Software": "Software and firmware specialist",
        "ProjectManagement": "Project management specialist",
    }
    missing = required.keys() - existing
    if not missing:
        return
    for code in missing:
        session.add(Agent(code=code, description=required[code]))
    session.commit()


def reset_engine() -> None:
    """Reset the cached engine (useful for tests)."""

    global _ENGINE
    _ENGINE = None
