"""Headers extraction endpoint for OpenRouter models."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, status

from ..models import HeaderItem, OpenRouterHeadersRequest
from ._headers_common import (
    build_header_messages,
    fetch_document_text,
    parse_and_store_headers,
)

router = APIRouter(prefix="/api/openrouter", tags=["headers"])


async def _chat_via_openrouter(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> str:
    """Call OpenRouter's OpenAI-compatible chat completions endpoint."""

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if params:
        referer = params.get("http_referer") or params.get("HTTP-Referer")
        if isinstance(referer, str) and referer.strip():
            headers["HTTP-Referer"] = referer.strip()
        x_title = params.get("x_title") or params.get("X-Title")
        if isinstance(x_title, str) and x_title.strip():
            headers["X-Title"] = x_title.strip()

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if params:
        for key in (
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
        ):
            if key in params:
                body[key] = params[key]

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            response = await client.post(endpoint, json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network errors
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter HTTP {exc.response.status_code}: {exc.response.text}",
            ) from exc
        except httpx.RequestError as exc:  # pragma: no cover - network errors
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter connection error: {exc!r}",
            ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter returned non-JSON: {response.text[:1000]}",
        ) from exc

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter unexpected response shape: {str(payload)[:1000]}",
        )
    first = choices[0] if isinstance(choices, list) else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter returned empty content: {str(payload)[:1000]}",
        )
    return content.strip()


@router.post("/headers", response_model=list[HeaderItem])
async def extract_openrouter_headers(
    payload: OpenRouterHeadersRequest,
) -> List[HeaderItem]:
    """Extract headers for an upload using an OpenRouter-hosted model."""

    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key is required for OpenRouter",
        )

    document = fetch_document_text(payload.upload_id)
    messages = build_header_messages(document)

    base_url = payload.base_url or "https://openrouter.ai/api/v1"
    timeout = float((payload.params or {}).get("timeout", 60.0))
    response_text = await _chat_via_openrouter(
        base_url=base_url,
        api_key=api_key,
        model=payload.model,
        messages=messages,
        params=payload.params,
        timeout=timeout,
    )
    return parse_and_store_headers(payload.upload_id, response_text)
