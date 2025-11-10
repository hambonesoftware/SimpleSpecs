"""Persistence helpers for header outline caching."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlmodel import Session, select

from ..models import HeaderOutlineCache, HeaderOutlineRun


def _sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 digest for ``data``."""

    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the SHA-256 digest for ``text`` interpreted as UTF-8."""

    return _sha256_bytes(text.encode("utf-8"))


def supersede_previous_runs(session: Session, document_id: int) -> None:
    """Mark completed runs for ``document_id`` as superseded."""

    runs = session.exec(
        select(HeaderOutlineRun).where(
            HeaderOutlineRun.document_id == document_id,
            HeaderOutlineRun.status == "completed",
        )
    ).all()
    if not runs:
        return
    for run in runs:
        run.status = "superseded"
    session.add_all(runs)
    session.commit()


def persist_outline_cache(
    session: Session,
    *,
    document_id: int,
    outline: Any,
    meta: Optional[dict],
    model: str,
    prompt_hash: str,
    source_hash: str,
    tokens_prompt: Optional[int] = None,
    tokens_completion: Optional[int] = None,
    latency_ms: Optional[int] = None,
    supersede_old: bool = False,
) -> int:
    """Persist a header outline run and its cached payload.

    Returns the database identifier of the created :class:`HeaderOutlineRun`.
    """

    if supersede_old:
        supersede_previous_runs(session, document_id)

    run = HeaderOutlineRun(
        document_id=document_id,
        model=model,
        prompt_hash=prompt_hash,
        source_hash=source_hash,
        status="completed",
    )
    session.add(run)
    session.flush()  # ensures ``run.id`` is available

    unique_key = f"{document_id}:{prompt_hash}:{source_hash}"
    cache = HeaderOutlineCache(
        run_id=run.id or 0,
        document_id=document_id,
        outline_json=json.dumps(outline, ensure_ascii=False),
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        latency_ms=latency_ms,
        unique_key=unique_key,
    )
    session.add(cache)
    session.commit()
    return int(run.id or 0)


def latest_outline_for_document(
    session: Session, document_id: int
) -> HeaderOutlineCache | None:
    """Return the most recent cached outline for ``document_id``."""

    statement = (
        select(HeaderOutlineCache)
        .where(HeaderOutlineCache.document_id == document_id)
        .order_by(HeaderOutlineCache.created_at.desc())
        .limit(1)
    )
    return session.exec(statement).first()


__all__ = [
    "latest_outline_for_document",
    "persist_outline_cache",
    "sha256_text",
    "supersede_previous_runs",
]
