"""Thin OpenRouter chat client with hardened parameter handling."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

import httpx

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


def _extract_max_tokens(params: Mapping[str, Any] | None) -> int | None:
    """Return an integer max token value from the provided params mapping."""

    if not params:
        return None
    for key in ("max_tokens", "max_new_tokens"):
        value = params.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


async def openrouter_chat(
    *,
    api_key: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    timeout: float,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Send a chat completion request to OpenRouter and return the response text."""

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    headers: MutableMapping[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    bigger: MutableMapping[str, Any] = dict(params or {})
    bigger["max_tokens"] = max(_extract_max_tokens(params) or 2048, 4096)

    if params:
        referer = params.get("http_referer") or params.get("HTTP-Referer")
        if isinstance(referer, str) and referer.strip():
            headers["HTTP-Referer"] = referer.strip()
        x_title = params.get("x_title") or params.get("X-Title")
        if isinstance(x_title, str) and x_title.strip():
            headers["X-Title"] = x_title.strip()

    payload_params = {
        key: value
        for key, value in bigger.items()
        if key not in {"http_referer", "HTTP-Referer", "x_title", "X-Title"}
        and value is not None
    }

    payload = {
        "model": model,
        "messages": [dict(message) for message in messages],
        **payload_params,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(BASE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter response missing choices array")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter response missing message content")
        return content


__all__ = ["openrouter_chat"]
