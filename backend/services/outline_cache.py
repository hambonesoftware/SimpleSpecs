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


def supersede_previous_runs(
    session: Session,
    document_id: int,
    *,
    exclude_run_id: int | None = None,
) -> None:
    """Mark completed runs for ``document_id`` as superseded.

    Parameters
    ----------
    session:
        Active database session.
    document_id:
        Identifier of the document whose runs should be superseded.
    exclude_run_id:
        Optional run identifier that should remain marked as ``completed``.
    """

    runs = session.exec(
        select(HeaderOutlineRun).where(
            HeaderOutlineRun.document_id == document_id,
            HeaderOutlineRun.status == "completed",
        )
    ).all()
    if not runs:
        return

    touched = False
    for run in runs:
        if exclude_run_id is not None and int(run.id or 0) == exclude_run_id:
            continue
        run.status = "superseded"
        touched = True

    if not touched:
        return

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

    Returns the identifier of the relevant :class:`HeaderOutlineRun`. The
    function is idempotent for the tuple ``(document_id, prompt_hash,
    source_hash)`` and will update the existing run/cache when invoked again
    with the same hashes.
    """

    unique_key = f"{document_id}:{prompt_hash}:{source_hash}"

    existing_run = session.exec(
        select(HeaderOutlineRun)
        .where(
            HeaderOutlineRun.document_id == document_id,
            HeaderOutlineRun.prompt_hash == prompt_hash,
            HeaderOutlineRun.source_hash == source_hash,
        )
        .order_by(HeaderOutlineRun.created_at.desc())
    ).first()

    if existing_run is None:
        run = HeaderOutlineRun(
            document_id=document_id,
            model=model,
            prompt_hash=prompt_hash,
            source_hash=source_hash,
            status="completed",
        )
        session.add(run)
        session.flush()
    else:
        run = existing_run
        run.model = model
        run.status = "completed"
        run.error = None
        session.add(run)
        session.flush()

    if supersede_old:
        supersede_previous_runs(session, document_id, exclude_run_id=int(run.id or 0))

    cache = session.exec(
        select(HeaderOutlineCache)
        .where(
            HeaderOutlineCache.document_id == document_id,
            HeaderOutlineCache.unique_key == unique_key,
        )
        .order_by(HeaderOutlineCache.created_at.desc())
    ).first()

    payload_json = json.dumps(outline, ensure_ascii=False)
    meta_json = json.dumps(meta or {}, ensure_ascii=False)

    if cache is None:
        cache = HeaderOutlineCache(
            run_id=int(run.id or 0),
            document_id=document_id,
            outline_json=payload_json,
            meta_json=meta_json,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            latency_ms=latency_ms,
            unique_key=unique_key,
        )
    else:
        cache.run_id = int(run.id or 0)
        cache.outline_json = payload_json
        cache.meta_json = meta_json
        cache.tokens_prompt = tokens_prompt
        cache.tokens_completion = tokens_completion
        cache.latency_ms = latency_ms

    session.add(cache)
    session.commit()
    return int(run.id or 0)


def latest_outline_for_document(
    session: Session, document_id: int
) -> HeaderOutlineCache | None:
    """Return the most recent cached outline for ``document_id``."""

    statement = (
        select(HeaderOutlineCache)
        .join(HeaderOutlineRun, HeaderOutlineRun.id == HeaderOutlineCache.run_id)
        .where(
            HeaderOutlineCache.document_id == document_id,
            HeaderOutlineRun.status == "completed",
        )
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
