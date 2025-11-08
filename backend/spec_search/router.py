"""FastAPI router exposing the spec-search pipeline."""
from __future__ import annotations

from fastapi import APIRouter

from backend.llm_client import create_default_client

from .extractor import extract_buckets
from .models import SpecSearchData, SpecSearchMeta, SpecSearchRequest, SpecSearchResponse
from .reporting import SpecSearchReporter

router = APIRouter()


@router.post("/api/spec-search", response_model=SpecSearchResponse)
async def run_spec_search(payload: SpecSearchRequest) -> SpecSearchResponse:
    """Execute the extraction pipeline and return the normalized response."""

    client = create_default_client()
    reporter = SpecSearchReporter()
    try:
        response = await extract_buckets(
            text=payload.text,
            buckets=payload.buckets,
            llm_client=client,
            reporter=reporter,
        )
        return response
    except Exception as exc:  # pragma: no cover - defensive
        meta = SpecSearchMeta(log_path=reporter.log_path)
        return SpecSearchResponse(
            ok=False,
            error=str(exc),
            data=SpecSearchData.empty(payload.buckets),
            meta=meta,
        )
