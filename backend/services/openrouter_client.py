"""Synchronous OpenRouter chat client used across the backend."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

import requests

log = logging.getLogger("openrouter")

OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"
).strip()
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
_DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat-v3-0324:free"
SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:3600").strip()
X_TITLE = os.getenv("OPENROUTER_X_TITLE", "SimpleSpecs (Dev)").strip()

try:  # Import lazily to avoid optional dependency issues during packaging.
    from ..config import get_settings
except Exception:  # pragma: no cover - fallback when config import fails
    get_settings = None  # type: ignore[assignment]


def _resolve_default_model() -> str:
    """Return the configured default model from settings or environment."""

    env_model = os.getenv("OPENROUTER_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()

    if get_settings is not None:
        try:
            settings = get_settings()
        except Exception:  # pragma: no cover - defensive cache failure
            settings = None
        if settings:
            configured = getattr(settings, "openrouter_model", "")
            if configured and isinstance(configured, str):
                configured = configured.strip()
                if configured:
                    return configured

    return _DEFAULT_OPENROUTER_MODEL


class OpenRouterError(RuntimeError):
    """Raised when the OpenRouter API request fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _extract_max_tokens(params: Mapping[str, Any] | None) -> int | None:
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


def _merge_payload(
    messages: List[Dict[str, str]],
    model: Optional[str],
    temperature: float,
    params: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    bigger: MutableMapping[str, Any] = dict(params or {})
    bigger["max_tokens"] = max(_extract_max_tokens(params) or 2048, 120_000)

    payload: Dict[str, Any] = {
        "model": model or _resolve_default_model(),
        "messages": messages,
        "temperature": temperature,
    }

    for key, value in bigger.items():
        if key in {"http_referer", "HTTP-Referer", "x_title", "X-Title"}:
            continue
        if value is not None:
            payload[key] = value

    return payload


def _merge_headers(headers: Mapping[str, str] | None) -> Dict[str, str]:
    merged: Dict[str, str] = {
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "Referer": SITE_URL,
        "X-Title": X_TITLE,
    }

    auth_header = None
    if headers:
        auth_header = headers.get("Authorization") or headers.get("authorization")
    if auth_header and auth_header.strip():
        token = auth_header.strip()
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        merged["Authorization"] = token
    elif OPENROUTER_KEY:
        merged["Authorization"] = f"Bearer {OPENROUTER_KEY}"
    else:
        raise OpenRouterError("Missing OPENROUTER_API_KEY")

    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            continue
        if not value:
            continue
        merged[key] = value.strip() if isinstance(value, str) else value

    referer = merged.get("HTTP-Referer") or merged.get("http_referer")
    if isinstance(referer, str) and referer.strip():
        merged["HTTP-Referer"] = referer.strip()
        merged.setdefault("Referer", referer.strip())
    else:
        merged["HTTP-Referer"] = SITE_URL
        merged.setdefault("Referer", SITE_URL)

    plain_referer = merged.get("Referer")
    if not isinstance(plain_referer, str) or not plain_referer.strip():
        merged["Referer"] = merged["HTTP-Referer"]

    x_title = merged.get("X-Title") or merged.get("x_title")
    if isinstance(x_title, str) and x_title.strip():
        merged["X-Title"] = x_title.strip()
    else:
        merged["X-Title"] = X_TITLE

    return merged


def chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.6,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_connect: int = 10,
    timeout_read: int = 120,
) -> str:
    """Send a chat completion request to OpenRouter and return the content."""

    if not OPENROUTER_URL.startswith("http"):
        raise OpenRouterError(f"Invalid OPENROUTER_URL: {OPENROUTER_URL!r}")

    payload = _merge_payload(messages, model, temperature, params)
    request_headers = _merge_headers(headers)

    raw_request = {
        "url": OPENROUTER_URL,
        "headers": request_headers,
        "payload": payload,
    }

    try:
        raw_request_text = json.dumps(raw_request, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        raw_request_text = str(raw_request)

    print("[SimpleSpecs] OpenRouter raw request:\n" + raw_request_text)

    safe_headers = dict(request_headers)
    if "Authorization" in safe_headers:
        safe_headers["Authorization"] = "***REDACTED***"

    log.debug(
        "OpenRouter request prepared",
        extra={
            "openrouter": {
                "url": OPENROUTER_URL,
                "headers": safe_headers,
                "payload": payload,
            }
        },
    )

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=request_headers,
            json=payload,
            timeout=(timeout_connect, timeout_read),
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        log.error("OpenRouter request failed: %s", exc)
        raise OpenRouterError("OpenRouter request failed") from exc

    if response.status_code != 200:
        snippet = response.text[:500]
        log.error(
            "OpenRouter error %s: %s", response.status_code, snippet
        )
        raise OpenRouterError(
            f"{response.status_code} {response.reason}",
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except json.JSONDecodeError as exc:  # pragma: no cover - unexpected payload
        log.error("OpenRouter invalid JSON: %s", response.text[:500])
        raise OpenRouterError("Invalid JSON from OpenRouter") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        log.error("OpenRouter bad shape: %s / %s", exc, data)
        raise OpenRouterError("No choices in OpenRouter response") from exc


__all__ = ["chat", "OpenRouterError"]

