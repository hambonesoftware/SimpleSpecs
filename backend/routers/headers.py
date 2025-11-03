"""Headers router that adds `force` semantics to Start Header Search.

This module replaces the previous compat shim by defining the /api/headers/{document_id}
route itself and threading a `force` flag into the underlying implementation.
On force:
  - previously stored sections/state for the document are purged
  - any on-disk LLM cache (if a helper is available) is purged
  - the orchestrator is invoked with cache-bypass semantics
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

# The existing implementation lives under backend/api/headers.py
from ..api import headers as headers_api
from ..database import get_session

# Optional purge helpers — if these modules/functions don't exist yet,
# the no-op fallbacks keep this router backward compatible.
try:
    from ..services.sections import delete_sections_for_document  # type: ignore
except Exception:  # pragma: no cover
    def delete_sections_for_document(session: Session, document_id: int) -> None:  # type: ignore
        return None

try:
    from ..services.state import reset_simple_headers_state  # type: ignore
except Exception:  # pragma: no cover
    def reset_simple_headers_state(session: Session, document_id: int) -> None:  # type: ignore
        return None

router = APIRouter(prefix="/api", tags=["headers"])


@router.post("/headers/{document_id}")
def compute_headers(
    document_id: int,
    *,
    force: bool = Query(
        False,
        description="Force new LLM headers; purge prior headers/sections and bypass caches.",
    ),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Compute headers for a document.

    If `force` is true, this will wipe prior header storage for the document
    and force a fresh LLM header extraction (skipping any caches).
    """
    if force:
        # 1) Purge previously persisted artifacts for this document.
        # These are safe to call even if there were no prior runs.
        try:
            delete_sections_for_document(session=session, document_id=document_id)
        except Exception:
            # Purge errors shouldn't block a new run.
            pass

        try:
            reset_simple_headers_state(session=session, document_id=document_id)
        except Exception:
            pass

        # 2) Optionally purge on-disk LLM cache if the api module exposes a helper.
        # This is best-effort and will silently continue on failure.
        try:
            purge_cache = getattr(headers_api, "purge_llm_cache_for_document", None)
            if callable(purge_cache):
                purge_cache(document_id)
        except Exception:
            pass

        # 3) Delegate to the existing API function: it takes (document_id[, force])
    try:
        # Newer implementations may support a 'force' kwarg; pass it when available.
        result = headers_api.extract_headers_and_chunks(document_id, force=force)  # type: ignore[call-arg]
    except TypeError:
        # Older signature without 'force'
        result = headers_api.extract_headers_and_chunks(document_id)  # type: ignore[misc]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Header extraction failed: {exc}") from exc


    if not result:
        raise HTTPException(status_code=500, detail="Header extraction returned no result")
    return result


# ---- Test patch points / public API compatibility --------------------------

# Keep these available for tests and external imports
parse_pdf = headers_api.parse_pdf
extract_headers_and_chunks = headers_api.extract_headers_and_chunks
HeadersLLMClient = headers_api.HeadersLLMClient

__all__ = [
    "router",
    "compute_headers",
    "parse_pdf",
    "extract_headers_and_chunks",
    "HeadersLLMClient",
]
