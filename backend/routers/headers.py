"""Headers extraction endpoint for OpenRouter models."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from httpx import InvalidURL

from ..models import HeaderItem, OpenRouterHeadersRequest
from ._headers_common import (
    build_header_messages,
    fetch_document_text,
    parse_and_store_headers,
)

router = APIRouter(prefix="/api/openrouter", tags=["headers"])
logger = logging.getLogger(__name__)

ALLOWED_OR_HOSTS = {"openrouter.ai", "api.openrouter.ai"}
_HEADERS_BLOCK_RE = re.compile(r"```#headers#\s*(.*?)```", re.DOTALL)


def _normalize_openrouter_base_url(raw_base_url: str | None) -> str:
    """Sanitize a user-supplied OpenRouter base URL."""

    base = (raw_base_url or "").strip().replace("\\", "/")
    if not base:
        return "https://openrouter.ai/api/v1"

    if "://" not in base:
        base = f"https://{base}"
    try:
        parsed = httpx.URL(base)
    except InvalidURL as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base_url: {exc}",
        ) from exc

    host = (parsed.host or "").lower()

    # Block obvious non-OpenRouter URLs early
    if any(
        marker in base.lower()
        for marker in (":11434", "/api/chat", "/v1/chat", "ollama", "openwebui")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url looks like an Ollama URL. Use https://openrouter.ai/api/v1 for OpenRouter.",
        )

    if host not in ALLOWED_OR_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url must be an OpenRouter endpoint, e.g. https://openrouter.ai/api/v1",
        )

    # Ensure path defaults to /api/v1
    path = parsed.raw_path.decode() if parsed.raw_path else ""
    if not path or path == "/":
        parsed = parsed.copy_with(raw_path=b"/api/v1")
    return str(parsed)


def _extract_max_tokens(params: Dict[str, Any] | None) -> Optional[int]:
    if not params:
        return None
    for key in (
        "max_tokens",
        "max_output_tokens",
        "max_completion_tokens",
        "max_new_tokens",
        "num_predict",
    ):
        value = params.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            limit = int(value)
        else:
            try:
                limit = int(str(value))
            except (TypeError, ValueError):
                continue
        if limit > 0:
            return limit
    return None


def _stringify_reasoning(reasoning: Any) -> str:
    if reasoning is None:
        return ""
    if isinstance(reasoning, str):
        return reasoning
    if isinstance(reasoning, dict):
        parts: list[str] = []
        for key in ("content", "text", "message"):
            value = reasoning.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value if item is not None)
        return "\n".join(parts)
    if isinstance(reasoning, list):
        parts: list[str] = []
        for item in reasoning:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(reasoning)


def _extract_headers_from_reasoning(reasoning: Any) -> Optional[str]:
    reasoning_text = _stringify_reasoning(reasoning)
    if not reasoning_text:
        return None
    match = _HEADERS_BLOCK_RE.search(reasoning_text)
    if not match:
        return None
    extracted = match.group(1).strip()
    return extracted or None


def _build_request_body(
    *,
    model: str,
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "modalities": ["text"],
        "response_format": {"type": "text"},
    }

    if not params:
        return body

    token_limit = _extract_max_tokens(params)
    if token_limit is not None:
        body["max_tokens"] = token_limit

    for key in (
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "stop",
    ):
        if key in params:
            body[key] = params[key]

    return body


async def _chat_via_openrouter(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 360.0,
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

    body = _build_request_body(model=model, messages=messages, params=params)

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            logger.debug("[headers] POST %s model=%s", endpoint, model)
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
    if not isinstance(message, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter missing message content: {str(payload)[:1000]}",
        )

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    fallback = _extract_headers_from_reasoning(message.get("reasoning"))
    if isinstance(fallback, str) and fallback:
        return fallback

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"OpenRouter returned empty content: {str(payload)[:1000]}",
    )


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

    base_url = _normalize_openrouter_base_url(payload.base_url)
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
