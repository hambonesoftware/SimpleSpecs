from __future__ import annotations

import hashlib
import json

from sqlmodel import Session, select

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, init_db, reset_database_state
from backend.models import Document, HeaderOutlineCache, HeaderOutlineRun
from backend.services.outline_cache import (
    latest_outline_for_document,
    persist_outline_cache,
    sha256_text,
)


def _prepare_db(monkeypatch, tmp_path) -> Session:
    db_path = tmp_path / "outline.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("EXPORT_RETENTION_DAYS", "1")
    monkeypatch.setenv("MAX_UPLOAD_SIZE", "1024")

    reset_settings_cache()
    reset_database_state()
    get_settings()
    init_db()

    engine = get_engine()
    return Session(engine)


def test_sha256_text_roundtrip() -> None:
    """``sha256_text`` should match the hashlib reference implementation."""

    sample = "Hello, SimpleSpecs!"
    expected = hashlib.sha256(sample.encode("utf-8")).hexdigest()
    assert sha256_text(sample) == expected


def test_persist_outline_cache_idempotent(monkeypatch, tmp_path) -> None:
    """Persisting the same outline twice should reuse the existing run."""

    with _prepare_db(monkeypatch, tmp_path) as session:
        document = Document(filename="doc.pdf", checksum="abc123")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

        outline = {"headers": [{"text": "Intro"}]}
        meta = {"model": "anthropic/claude-3.5-sonnet"}

        run_id_1 = persist_outline_cache(
            session,
            document_id=document_id,
            outline=outline,
            meta=meta,
            model="anthropic/claude-3.5-sonnet",
            prompt_hash="prompt-1",
            source_hash="source-1",
            supersede_old=True,
        )

        # Second call with the same hashes should reuse the run.
        run_id_2 = persist_outline_cache(
            session,
            document_id=document_id,
            outline={"headers": [{"text": "Intro", "level": 1}]},
            meta={"model": "anthropic/claude-3.5-sonnet", "extra": True},
            model="anthropic/claude-3.5-sonnet",
            prompt_hash="prompt-1",
            source_hash="source-1",
            supersede_old=True,
        )

        assert run_id_1 == run_id_2

        cache_entries = session.exec(
            select(HeaderOutlineCache).where(HeaderOutlineCache.document_id == document_id)
        ).all()
        assert len(cache_entries) == 1
        stored_outline = json.loads(cache_entries[0].outline_json)
        assert stored_outline["headers"][0]["level"] == 1

        # Persisting a new prompt should create a new run and supersede the prior one.
        run_id_3 = persist_outline_cache(
            session,
            document_id=document_id,
            outline={"headers": [{"text": "Scope"}]},
            meta=meta,
            model="anthropic/claude-3.5-sonnet",
            prompt_hash="prompt-2",
            source_hash="source-1",
            supersede_old=True,
        )
        assert run_id_3 != run_id_2

        runs = session.exec(
            select(HeaderOutlineRun).where(HeaderOutlineRun.document_id == document_id)
        ).all()
        statuses = {run.prompt_hash: run.status for run in runs}
        assert statuses == {"prompt-1": "superseded", "prompt-2": "completed"}


def test_latest_outline_for_document_skips_non_completed(monkeypatch, tmp_path) -> None:
    """``latest_outline_for_document`` should ignore non-completed runs."""

    with _prepare_db(monkeypatch, tmp_path) as session:
        document = Document(filename="doc.pdf", checksum="cache-test")
        session.add(document)
        session.commit()
        session.refresh(document)
        document_id = int(document.id or 0)

        # Persist a completed run.
        persist_outline_cache(
            session,
            document_id=document_id,
            outline={"headers": [{"text": "Intro"}]},
            meta={"model": "anthropic/claude-3.5-sonnet"},
            model="anthropic/claude-3.5-sonnet",
            prompt_hash="completed",
            source_hash="source-1",
            supersede_old=False,
        )

        # Manually add a failed run which should be ignored by ``latest_outline_for_document``.
        failed_run = HeaderOutlineRun(
            document_id=document_id,
            model="anthropic/claude-3.5-sonnet",
            prompt_hash="failed",
            source_hash="source-1",
            status="failed",
        )
        session.add(failed_run)
        session.flush()
        session.add(
            HeaderOutlineCache(
                run_id=int(failed_run.id or 0),
                document_id=document_id,
                outline_json=json.dumps({"headers": []}),
                meta_json=json.dumps({}),
            )
        )
        session.commit()

        latest = latest_outline_for_document(session, document_id)
        assert latest is not None
        assert json.loads(latest.outline_json)["headers"][0]["text"] == "Intro"
