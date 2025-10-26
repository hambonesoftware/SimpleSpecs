"""Routes that expose operational observability data."""

from __future__ import annotations
from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from backend import __version__
from ..database import get_engine
from ..observability import metrics_registry

router = APIRouter(prefix="/api", tags=["observability"])


def _database_ok() -> bool:
    """Run a lightweight database check."""

    engine = get_engine()
    try:
        with Session(engine) as session:
            session.exec(select(1)).one()
    except SQLAlchemyError:
        return False
    return True


@router.get("/metrics")
def read_metrics() -> dict[str, object]:
    """Return the current request metrics snapshot."""

    return metrics_registry.snapshot()


@router.get("/status")
def read_status() -> dict[str, object]:
    """Return an aggregated operational status payload."""

    return {
        "app": {"version": __version__},
        "database": {"ok": _database_ok()},
        "metrics": metrics_registry.snapshot(),
    }


__all__ = ["router"]
