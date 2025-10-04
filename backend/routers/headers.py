"""Headers extraction endpoint (with minimal OpenRouter direct-call support)."""
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, status

from ..models import HeaderItem, HeadersRequest
from ..services.llm import get_provider
from ..services.text_blocks import document_text
from ..store import headers_path, read_jsonl, upload_objects_path, write_json

router = APIRouter(prefix="/api")

_HEADERS_PROMPT = """Please show a simple numbered nested list of all headers and subheaders for this document.
Return ONLY the list enclosed in #headers# fencing, like:

#headers#
1. Top Level
   1.1 Sub
      1.1.1 Sub-sub
2. Another Top
#headers#
"""

# ---------------------------
# Minimal OpenRouter helpers
# ---------------------------

def _is_openrouter(base_url: Optional[str], provider_name: Optional[str]) -> bool:
    """Detect OpenRouter by base_url or explicit provider name."""
    if base_url and "openrouter.ai" in base_url:
        return True
    if provider_name and provider_name.lower() in {"openrouter", "openrouter.ai"}:
        return True
    return False


async def _chat_via_openrouter(
    *,
    base_url: str,
    api_key: str,
    model: Optional[str],
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> str:
    """
    Minimal OpenRouter call using OpenAI-compatible /chat/completions.
    Sends OpenAI-style payload and extracts choices[0].message.content.
    """
    if not base_url.rstrip("/").endswith("/chat/completions"):
        base_url = base_url.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Optional, but recommended by OpenRouter; safe no-ops if not provided.
    # Callers can pass these via payload.params if desired.
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

    # Pass through a few common OpenAI-style params when present.
    if params:
        for k in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty", "stop"):
            if k in params:
                body[k] = params[k]

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            resp = await client.post(base_url, json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter HTTP {resp.status_code}: {resp.text}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter connection error: {e!r}",
            ) from e

        try:
            data = resp.json()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter returned non-JSON: {resp.text[:1000]}",
            )

    # Extract OpenAI-like response
    if not isinstance(data, dict) or "choices" not in data or not data["choices"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter unexpected response shape: {str(data)[:1000]}",
        )

    first = data["choices"][0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter returned empty content: {str(data)[:1000]}",
        )
    return content.strip()

# ---------------------------
# Endpoint
# ---------------------------

@router.post("/headers", response_model=list[HeaderItem])
async def extract_headers(payload: HeadersRequest) -> List[HeaderItem]:
    objects_raw = read_jsonl(upload_objects_path(payload.upload_id))
    if not objects_raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    document = document_text(objects_raw)
    if not document.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is empty")

    messages = [
        {"role": "system", "content": "You analyze engineering specification documents."},
        {
            "role": "user",
            "content": f"{_HEADERS_PROMPT}\n\nDocument contents:\n{document}",
        },
    ]

    # Minimal change: if OpenRouter is detected, call it directly with OpenAI-style messaging.
    if _is_openrouter(payload.base_url, payload.provider):
        if not payload.api_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="api_key is required for OpenRouter")
        if not payload.base_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="base_url is required for OpenRouter")
        if not payload.model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model is required for OpenRouter")

        response_text = await _chat_via_openrouter(
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            messages=messages,
            params=payload.params,
            timeout=float((payload.params or {}).get("timeout", 60.0)),
        )
    else:
        # Default path: use your provider abstraction exactly as before.
        provider = get_provider(
            payload.provider,
            model=payload.model,
            params=payload.params,
            api_key=payload.api_key,
            base_url=payload.base_url,
        )
        response_text = await provider.chat(messages)

    match = re.search(r"#headers#(.*?)#headers#", response_text, re.DOTALL | re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM returned unexpected format")

    content = match.group(1)
    headers: list[HeaderItem] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match_line = re.match(r"^(\d+(?:\.\d+)*)[\s\-\.]+(.+)$", line)
        if not match_line:
            continue
        section_number = match_line.group(1).strip()
        section_name = match_line.group(2).strip()
        headers.append(HeaderItem(section_number=section_number, section_name=section_name))

    if not headers:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No headers parsed")

    write_json(headers_path(payload.upload_id), [header.model_dump() for header in headers])
    return headers
