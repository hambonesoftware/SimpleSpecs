"""Headers extraction endpoint for llama.cpp/Ollama models."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter

from ..models import HeaderItem, OllamaHeadersRequest
from ..services.llm import get_provider
from ._headers_common import (
    build_header_messages,
    clean_document_for_headers,
    fetch_document_text,
    parse_and_store_headers,
)

router = APIRouter(prefix="/api/ollama", tags=["headers"])


@router.post("/headers", response_model=list[HeaderItem])
async def extract_ollama_headers(payload: OllamaHeadersRequest) -> List[HeaderItem]:
    """Extract headers for an upload using a llama.cpp-compatible endpoint."""

    document = fetch_document_text(payload.upload_id)
    cleaned_document = clean_document_for_headers(document)
    messages = build_header_messages(cleaned_document)

    provider = get_provider(
        "llamacpp",
        model=payload.model,
        params=payload.params,
        base_url=payload.base_url.strip(),
    )
    response_text = await provider.chat(messages)
    return parse_and_store_headers(
        payload.upload_id,
        response_text,
        cleaned_document=cleaned_document,
    )
