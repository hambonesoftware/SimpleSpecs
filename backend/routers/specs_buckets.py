
"""
Specs Buckets endpoints: wipe + re-run buckets for a document.
Drop-in router that you can include from your FastAPI app.
- DELETE /api/specs/{document_id}/buckets  -> clears cached bucket artifacts (best-effort)
- POST   /api/specs/{document_id}/buckets/run-again -> runs all buckets concurrently and stores results
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

try:
    # project-local helpers
    from backend.config import get_settings, Settings
    from backend.database import get_session
    from backend.models import Document, DocumentArtifactType
    from backend.services.artifact_store import (
        get_cached_artifact, store_artifact
    )
    from backend.services.artifact_store import delete_artifact as _delete_artifact  # optional in older revs
    from backend.services.spec_records import (
        store_spec_buckets_result,
        wipe_spec_buckets_for_document,
    )
    from backend.services.specs_worker import (
        run_all_buckets_concurrently,
        BUCKET_ARTIFACT_KEY,
        SPEC_BUCKET_ARTIFACT_TYPE,
    )
    from backend.utils.spec_trace import SpecTracer
    from backend.services.documents import get_document_or_404  # if present
except Exception:
    # minimal fallbacks to keep this file importable even if some modules moved
    from backend.config import get_settings, Settings  # type: ignore
    from backend.database import get_session  # type: ignore
    from backend.services.artifact_store import store_artifact  # type: ignore
    from backend.services.specs_worker import (
        run_all_buckets_concurrently,
        BUCKET_ARTIFACT_KEY,
        SPEC_BUCKET_ARTIFACT_TYPE,
    )  # type: ignore
    from backend.services.spec_records import (  # type: ignore
        store_spec_buckets_result,
        wipe_spec_buckets_for_document,
    )
    from backend.utils.spec_trace import SpecTracer  # type: ignore

    def get_document_or_404(session: Session, document_id: int) -> Document:  # type: ignore
        from backend.models import Document  # type: ignore
        doc = session.get(Document, document_id)  # type: ignore
        if not doc:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return doc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/specs", tags=["specs"])


def _artifact_inputs(doc_hash: str | None = None) -> Dict[str, Any]:
    # Used so deletes/overwrites only touch the right run.
    inputs = {"kind": "spec_buckets"}
    if doc_hash:
        inputs["doc_hash"] = doc_hash
    logger.debug(
        "[specs_buckets] _artifact_inputs",
        {"doc_hash": doc_hash, "inputs": inputs},
    )
    return inputs


@router.delete("/{document_id}/buckets", response_class=Response)
def delete_buckets_cache(
    document_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Best-effort purge of cached Spec Bucket artifacts for the given document.
    Safe to call even if cache is empty or the delete helper isn't present.
    """
    logger.debug("[specs_buckets] delete_buckets_cache invoked", {"document_id": document_id})
    doc = get_document_or_404(session, document_id)
    logger.debug(
        "[specs_buckets] delete_buckets_cache resolved document",
        {
            "document_id": document_id,
            "doc_hash": getattr(doc, "doc_hash", None) or getattr(doc, "hash", None),
            "filename": getattr(doc, "filename", None),
        },
    )

    # Clear any persisted spec record payload before wiping cached artifacts.
    try:
        logger.debug("[specs_buckets] delete_buckets_cache wiping spec record", {"document_id": document_id})
        wipe_spec_buckets_for_document(session, document_id=document_id)
    except Exception:
        logger.exception("[specs_buckets] delete_buckets_cache wipe failed", exc_info=True)
        pass

    # Fetch a doc_hash if you store it on Document; otherwise skip (inputs filter remains generic).
    doc_hash = getattr(doc, "doc_hash", None) or getattr(doc, "hash", None)
    logger.debug(
        "[specs_buckets] delete_buckets_cache using doc_hash",
        {"document_id": document_id, "doc_hash": doc_hash},
    )

    # Try targeted delete if helper is available
    try:
        _ = _delete_artifact  # type: ignore[name-defined]
    except Exception:
        logger.debug("[specs_buckets] delete_buckets_cache delete helper unavailable")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        _delete_artifact(
            session=session,
            document_id=doc.id,
            artifact_type=SPEC_BUCKET_ARTIFACT_TYPE,
            key=BUCKET_ARTIFACT_KEY,
            inputs_like=_artifact_inputs(doc_hash),
        )
    except Exception:
        # swallow; we only want to make "Run again" never crash
        logger.exception("[specs_buckets] delete_buckets_cache delete_artifact raised", exc_info=True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    logger.debug("[specs_buckets] delete_buckets_cache completed", {"document_id": document_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/buckets/run-again")
async def run_again(
    document_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """
    Wipes cached bucket results (best-effort) then re-runs all bucket prompts concurrently.
    Returns a JSON object: {"ok": true, "buckets": {...}, "messages": [...]}.
    """
    tracer = SpecTracer(metadata={"trigger": "run_again", "document_id": document_id})
    tracer.function_call("run_again", document_id=document_id)
    logger.debug("[specs_buckets] run_again invoked", {"document_id": document_id})

    trace_path: str | None = None
    result: Dict[str, Any] | None = None
    stored_record = None
    artifact_stored = False

    try:
        # Purge cache first (no-op if unavailable)
        try:
            logger.debug("[specs_buckets] run_again calling delete_buckets_cache", {"document_id": document_id})
            delete_buckets_cache(document_id, session=session, settings=settings)  # type: ignore[arg-type]
            tracer.decision("delete_buckets_cache", status="ok", document_id=document_id)
        except Exception as exc:
            logger.exception("[specs_buckets] run_again delete_buckets_cache raised", exc_info=True)
            tracer.decision(
                "delete_buckets_cache",
                status="error",
                document_id=document_id,
                error=str(exc),
            )

        # Resolve document and run the worker
        doc = get_document_or_404(session, document_id)
        doc_hash = getattr(doc, "doc_hash", None) or getattr(doc, "hash", None)
        filename = getattr(doc, "filename", None)
        tracer.metadata(document_hash=doc_hash, document_filename=filename)
        logger.debug(
            "[specs_buckets] run_again resolved document",
            {
                "document_id": document_id,
                "doc_hash": doc_hash,
                "filename": filename,
            },
        )

        # Ensure any previous spec payload is cleared so the new run stores a fresh draft.
        try:
            logger.debug("[specs_buckets] run_again wiping spec record", {"document_id": document_id})
            wipe_spec_buckets_for_document(session, document_id=document_id)
            tracer.decision("wipe_spec_record", status="ok", document_id=document_id)
        except Exception as exc:
            logger.exception("[specs_buckets] run_again wipe_spec_buckets_for_document raised", exc_info=True)
            tracer.decision(
                "wipe_spec_record",
                status="error",
                document_id=document_id,
                error=str(exc),
            )

        # Expect PDFs to already be parsed/available on disk; we only need the text content.
        # The worker will fetch the parsed text (via artifact store) or re-parse if necessary.
        try:
            result = await run_all_buckets_concurrently(
                session=session,
                document=doc,
                settings=settings,
                tracer=tracer,
            )
        except Exception as exc:
            tracer.outcome(
                "run_again_worker",
                document_id=document_id,
                ok=False,
                error=str(exc),
            )
            raise

        tracer.decision(
            "worker_result",
            document_id=document_id,
            bucket_count=len(result.get("buckets", {})),
            message_count=len(result.get("messages", [])),
            doc_hash=result.get("doc_hash"),
        )
        logger.debug(
            "[specs_buckets] run_again worker result",
            {
                "document_id": document_id,
                "result_keys": list(result.keys()),
                "messages": result.get("messages"),
            },
        )

        # Persist a single artifact blob with all bucket outputs for this doc.
        try:
            logger.debug("[specs_buckets] run_again storing artifact", {"document_id": document_id})
            store_artifact(
                session=session,
                document_id=doc.id,
                artifact_type=SPEC_BUCKET_ARTIFACT_TYPE,
                key=BUCKET_ARTIFACT_KEY,
                inputs=_artifact_inputs(result.get("doc_hash")),
                body=result,
            )
            tracer.decision("store_artifact", status="ok", document_id=document_id)
            artifact_stored = True
        except Exception as exc:
            # Do not fail the request just because caching failed.
            logger.exception("[specs_buckets] run_again store_artifact raised", exc_info=True)
            tracer.decision(
                "store_artifact",
                status="error",
                document_id=document_id,
                error=str(exc),
            )

        try:
            logger.debug("[specs_buckets] run_again storing spec record", {"document_id": document_id})
            stored_record = store_spec_buckets_result(
                session,
                document_id=document_id,
                payload=result,
            )
            tracer.decision(
                "store_spec_record",
                status="ok",
                document_id=document_id,
                record_id=getattr(stored_record, "id", None),
            )
        except Exception as exc:
            logger.exception("[specs_buckets] run_again store_spec_buckets_result raised", exc_info=True)
            tracer.decision(
                "store_spec_record",
                status="error",
                document_id=document_id,
                error=str(exc),
            )

        tracer.outcome(
            "run_again",
            document_id=document_id,
            ok=True,
            artifact_stored=artifact_stored,
            record_stored=stored_record is not None,
        )

    except Exception:
        tracer.outcome("run_again", document_id=document_id, ok=False)
        trace_path = tracer.flush()
        raise
    finally:
        if trace_path is None:
            trace_path = tracer.flush()

    assert result is not None  # for mypy/static tools
    result["trace_path"] = trace_path

    response: Dict[str, Any] = {"ok": True, **result, "persisted": stored_record is not None}
    metadata = response.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        response["metadata"] = metadata
    metadata["trace_path"] = trace_path
    logger.debug(
        "[specs_buckets] run_again response summary",
        {
            "document_id": document_id,
            "persisted": stored_record is not None,
            "response_keys": list(response.keys()),
        },
    )
    if stored_record is not None:
        response["record"] = {
            "id": stored_record.id,
            "state": stored_record.state,
            "updated_at": stored_record.updated_at.isoformat()
            if stored_record.updated_at
            else None,
        }
        logger.debug(
            "[specs_buckets] run_again stored record",
            {
                "document_id": document_id,
                "record_id": stored_record.id,
                "state": stored_record.state,
            },
        )

    return response
