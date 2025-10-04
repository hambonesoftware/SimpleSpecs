"""API routes for managing persisted model settings."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session, init_db
from ..models_db import ModelSettings, ModelSettingsRead, ModelSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Ensure tables are created when the router is imported.
init_db()


def _fetch_current(session: Session) -> ModelSettings | None:
    return session.exec(select(ModelSettings).limit(1)).first()


@router.get("", response_model=ModelSettingsRead)
def read_model_settings(session: Session = Depends(get_session)) -> ModelSettings:
    """Return the persisted model settings, creating defaults if necessary."""

    record = _fetch_current(session)
    if record is None:
        record = ModelSettings()
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


@router.put("", response_model=ModelSettingsRead)
def update_model_settings(
    payload: ModelSettingsUpdate, session: Session = Depends(get_session)
) -> ModelSettings:
    """Persist the provided model settings payload."""

    record = _fetch_current(session)
    data = payload.model_dump()
    if record is None:
        record = ModelSettings(**data)
        session.add(record)
    else:
        for field, value in data.items():
            setattr(record, field, value)
        record.updated_at = datetime.now(timezone.utc)
        session.add(record)
    session.commit()
    session.refresh(record)
    return record
