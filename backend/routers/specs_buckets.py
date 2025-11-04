
"""
Specs Buckets endpoints: wipe + re-run buckets for a document.
Drop-in router that you can include from your FastAPI app.
- DELETE /api/specs/{document_id}/buckets  -> clears cached bucket artifacts (best-effort)
- POST   /api/specs/{document_id}/buckets/run-again -> runs all buckets concurrently and stores results
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
    from backend.services.specs_worker import (
        run_all_buckets_concurrently,
        BUCKET_ARTIFACT_KEY,
        SPEC_BUCKET_ARTIFACT_TYPE,
    )
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

    def get_document_or_404(session: Session, document_id: int) -> Document:  # type: ignore
        from backend.models import Document  # type: ignore
        doc = session.get(Document, document_id)  # type: ignore
        if not doc:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return doc

router = APIRouter(prefix="/api/specs", tags=["specs"])


def _artifact_inputs(doc_hash: str | None = None) -> Dict[str, Any]:
    # Used so deletes/overwrites only touch the right run.
    inputs = {"kind": "spec_buckets"}
    if doc_hash:
        inputs["doc_hash"] = doc_hash
    return inputs


@router.delete("/{document_id}/buckets", status_code=status.HTTP_204_NO_CONTENT)
def delete_buckets_cache(
    document_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Best-effort purge of cached Spec Bucket artifacts for the given document.
    Safe to call even if cache is empty or the delete helper isn't present.
    """
    doc = get_document_or_404(session, document_id)

    # Fetch a doc_hash if you store it on Document; otherwise skip (inputs filter remains generic).
    doc_hash = getattr(doc, "doc_hash", None) or getattr(doc, "hash", None)

    # Try targeted delete if helper is available
    try:
        _ = _delete_artifact  # type: ignore[name-defined]
    except Exception:
        return  # older artifact store without delete; nothing to do

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
        return


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
    # Purge cache first (no-op if unavailable)
    try:
        delete_buckets_cache(document_id, session=session, settings=settings)  # type: ignore[arg-type]
    except Exception:
        pass

    # Resolve document and run the worker
    doc = get_document_or_404(session, document_id)
    # Expect PDFs to already be parsed/available on disk; we only need the text content.
    # The worker will fetch the parsed text (via artifact store) or re-parse if necessary.
    result = await run_all_buckets_concurrently(
        session=session,
        document=doc,
        settings=settings,
    )

    # Persist a single artifact blob with all bucket outputs for this doc.
    try:
        store_artifact(
            session=session,
            document_id=doc.id,
            artifact_type=SPEC_BUCKET_ARTIFACT_TYPE,
            key=BUCKET_ARTIFACT_KEY,
            inputs=_artifact_inputs(result.get("doc_hash")),
            body=result,
        )
    except Exception:
        # Do not fail the request just because caching failed.
        pass

    return {"ok": True, **result}
