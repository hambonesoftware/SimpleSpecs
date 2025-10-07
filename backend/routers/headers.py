"""Headers extraction endpoint for OpenRouter models (EXTREMELY VERBOSE)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from httpx import InvalidURL

from ..models import HeaderItem, OpenRouterHeadersRequest
from ._headers_common import (
    build_header_messages,
    clean_document_for_headers,
    fetch_document_text,
    parse_and_store_headers,
)

# ---------------------------
# Router / Logger
# ---------------------------
router = APIRouter(prefix="/api/openrouter", tags=["headers"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------
# Constants / Regex
# ---------------------------
ALLOWED_OR_HOSTS = {"openrouter.ai", "api.openrouter.ai"}

# Accept BOTH styles:
# 1) fenced: ```#headers# ... ```
# 2) plain markers: #headers# ... #headers#
_HEADERS_BLOCK_RE_FENCED = re.compile(r"```#headers#\s*(.*?)```", re.DOTALL)
_HEADERS_BLOCK_RE_PLAIN = re.compile(r"#headers#\s*(.*?)\s*#headers#", re.DOTALL)

# ---------------------------
# Debug helpers
# ---------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


DEBUG_DIR = Path(os.getenv("HEADERS_DEBUG_DIR", ".cache/headers_openrouter"))
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
TEXT_PREVIEW = _env_int("HEADERS_MAX_TEXT_PREVIEW", 1200)
MIN_MAX_TOKENS = _env_int("HEADERS_MIN_MAX_TOKENS", 4096)  # floor for any provided max_tokens-ish


@dataclass
class DebugCtx:
    upload_id: str
    request_id: str
    base_url: str = ""
    endpoint: str = ""
    model: str = ""
    debug_dir: Path = DEBUG_DIR

    def path(self, name: str) -> Path:
        return self.debug_dir / f"{self.upload_id}__{self.request_id}__{name}"


def _redact(s: Any) -> Any:
    """Redact obvious secrets (API keys) in dicts/strings."""

    if s is None:
        return s
    if isinstance(s, str):
        if s.startswith("sk-") or len(s) > 24:
            # Heuristic redaction for keys in strings
            return s[:6] + "…" + s[-4:]
        return s
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            lk = str(k).lower()
            if "authorization" in lk or "api_key" in lk or "apikey" in lk or "bearer" in lk:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(s, list):
        return [_redact(x) for x in s]
    return s


def _shorten(txt: Optional[str], n: int = TEXT_PREVIEW) -> Optional[str]:
    if not isinstance(txt, str):
        return txt
    return txt if len(txt) <= n else txt[:n] + " …[truncated]"


def _dump_json(ctx: DebugCtx, filename: str, obj: Any) -> None:
    try:
        p = ctx.path(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:  # pragma: no cover - best effort debug logging
        logger.debug("[headers][%s][dump] failed to write %s: %r", ctx.request_id, filename, e)


def _dump_evidence(ctx: DebugCtx, title: str, snippet: Optional[str], tag: str) -> None:
    if ctx is None or snippet is None:
        return
    try:
        safe_title = re.sub(r"[^A-Za-z0-9_\-]+", "_", title).strip("_")[:60] or "header"
        path = ctx.path(f"evidence_{tag}__{safe_title}.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snippet, encoding="utf-8")
    except Exception as exc:  # pragma: no cover - best effort debug logging
        logger.debug(
            "[headers][%s][dump] failed to write evidence for %s: %r",
            ctx.request_id,
            title,
            exc,
        )


def _time_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


# ---------------------------
# Normalizers / Builders
# ---------------------------


def _normalize_openrouter_base_url(
    raw_base_url: str | None, ctx: Optional[DebugCtx] = None
) -> str:
    """Sanitize a user-supplied OpenRouter base URL."""

    base = (raw_base_url or "").strip().replace("\\", "/")
    if not base:
        base = "https://openrouter.ai/api/v1"

    if "://" not in base:
        base = f"https://{base}"
    try:
        parsed = httpx.URL(base)
    except InvalidURL as exc:
        detail = f"Invalid base_url: {exc}"
        if ctx:
            logger.error("[headers][%s] %s", ctx.request_id, detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    host = (parsed.host or "").lower()

    # Block obvious non-OpenRouter URLs early
    if any(
        marker in base.lower()
        for marker in (":11434", "/api/chat", "/v1/chat", "ollama", "openwebui")
    ):
        detail = "base_url looks like an Ollama URL. Use https://openrouter.ai/api/v1 for OpenRouter."
        if ctx:
            logger.error("[headers][%s] %s (base_url=%s)", ctx.request_id, detail, base)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if host not in ALLOWED_OR_HOSTS:
        detail = "base_url must be an OpenRouter endpoint, e.g. https://openrouter.ai/api/v1"
        if ctx:
            logger.error("[headers][%s] %s (host=%s)", ctx.request_id, detail, host)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # Ensure path defaults to /api/v1
    path = parsed.raw_path.decode() if parsed.raw_path else ""
    if not path or path == "/":
        parsed = parsed.copy_with(raw_path=b"/api/v1")
    final = str(parsed)
    if ctx:
        logger.debug("[headers][%s] normalized base_url=%s", ctx.request_id, final)
    return final


def _extract_max_tokens(params: Dict[str, Any] | None, ctx: Optional[DebugCtx] = None) -> Optional[int]:
    if not params:
        if ctx:
            logger.debug("[headers][%s] no params provided; not setting max tokens", ctx.request_id)
        return None
    candidates = (
        "max_tokens",
        "max_output_tokens",
        "max_completion_tokens",
        "max_new_tokens",
        "num_predict",
    )
    for key in candidates:
        value = params.get(key)
        if value is None:
            continue
        try:
            limit = int(value)
            if limit > 0:
                # enforce a configurable floor to reduce truncation surprises
                limit = max(limit, MIN_MAX_TOKENS)
                if ctx:
                    logger.debug(
                        "[headers][%s] using max_tokens=%s (from %s, floored to >= %s)",
                        ctx.request_id,
                        limit,
                        key,
                        MIN_MAX_TOKENS,
                    )
                return limit
        except Exception:
            continue
    if ctx:
        logger.debug("[headers][%s] no explicit max_tokens; not setting one", ctx.request_id)
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


def _extract_headers_from_reasoning(reasoning: Any, ctx: Optional[DebugCtx] = None) -> Optional[str]:
    reasoning_text = _stringify_reasoning(reasoning)
    if ctx:
        logger.debug(
            "[headers][%s] reasoning preview: %s", ctx.request_id, _shorten(reasoning_text)
        )
    if not reasoning_text:
        return None
    m1 = _HEADERS_BLOCK_RE_FENCED.search(reasoning_text)
    if m1:
        extracted = (m1.group(1) or "").strip()
        if ctx:
            logger.debug(
                "[headers][%s] found fenced headers block in reasoning (%d chars)",
                ctx.request_id,
                len(extracted),
            )
        return extracted or None
    m2 = _HEADERS_BLOCK_RE_PLAIN.search(reasoning_text)
    if m2:
        extracted = (m2.group(1) or "").strip()
        if ctx:
            logger.debug(
                "[headers][%s] found plain headers block in reasoning (%d chars)",
                ctx.request_id,
                len(extracted),
            )
        return extracted or None
    if ctx:
        logger.debug("[headers][%s] no headers block found in reasoning", ctx.request_id)
    return None


def _build_request_body(
    *,
    model: str,
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]],
    ctx: Optional[DebugCtx] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "modalities": ["text"],
        "response_format": {"type": "text"},
    }
    if not params:
        if ctx:
            logger.debug("[headers][%s] no params provided; using defaults", ctx.request_id)
        return body

    token_limit = _extract_max_tokens(params, ctx=ctx)
    if token_limit is not None:
        body["max_tokens"] = token_limit

    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "stop"):
        if key in params:
            body[key] = params[key]
            if ctx:
                logger.debug(
                    "[headers][%s] param passthrough: %s=%r",
                    ctx.request_id,
                    key,
                    params[key],
                )

    return body


# ---------------------------
# OpenRouter call
# ---------------------------


async def _chat_via_openrouter(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 360.0,
    ctx: Optional[DebugCtx] = None,
) -> str:
    """Call OpenRouter's OpenAI-compatible chat completions endpoint (very verbose)."""

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    if ctx:
        ctx.endpoint = endpoint

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

    body = _build_request_body(model=model, messages=messages, params=params, ctx=ctx)

    # Log & dump request (redacted)
    safe_headers = _redact(headers)
    safe_body = _redact(body)
    if ctx:
        _dump_json(
            ctx,
            "openrouter_request.json",
            {"endpoint": endpoint, "headers": safe_headers, "body": safe_body},
        )
        # Also summarize messages to avoid massive logs
        logger.debug(
            "[headers][%s] POST %s model=%s messages=%d (sys/user lengths preview) | headers=%s",
            ctx.request_id,
            endpoint,
            model,
            len(messages),
            {m.get("role"): len(m.get("content", "")) for m in messages[:2]},
        )

    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            response = await client.post(endpoint, json=body)
            elapsed = _time_ms(t0)
            if ctx:
                logger.debug("[headers][%s] HTTP %s in %d ms", ctx.request_id, response.status_code, elapsed)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network errors
            status_code = exc.response.status_code if exc.response is not None else "???"
            text_snip = _shorten(exc.response.text if exc.response is not None else "", 800)
            if ctx:
                _dump_json(
                    ctx,
                    "openrouter_http_error.json",
                    {
                        "status": int(status_code) if isinstance(status_code, int) else status_code,
                        "text_snippet": text_snip,
                    },
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter HTTP {status_code}: {text_snip}",
            ) from exc
        except httpx.RequestError as exc:  # pragma: no cover - network errors
            if ctx:
                _dump_json(ctx, "openrouter_request_error.json", {"error": repr(exc)})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenRouter connection error: {exc!r}",
            ) from exc

    # Try to parse JSON
    try:
        payload = response.json()
    except ValueError as exc:
        snip = _shorten(response.text, 1000)
        if ctx:
            _dump_json(ctx, "openrouter_non_json.json", {"text_snippet": snip})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter returned non-JSON: {snip}",
        ) from exc

    if ctx:
        _dump_json(ctx, "openrouter_response.json", payload)

    # Common error shape from OpenRouter
    if isinstance(payload, dict) and "error" in payload:
        err = payload.get("error")
        snip = _shorten(json.dumps(err, ensure_ascii=False), 800)
        if ctx:
            logger.error("[headers][%s] OpenRouter error: %s", ctx.request_id, snip)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter error: {snip}",
        )

    # choices/message/content
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        snip = _shorten(json.dumps(payload, ensure_ascii=False), 1000)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter unexpected response shape: {snip}",
        )
    first = choices[0] if isinstance(choices, list) else None
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        snip = _shorten(json.dumps(payload, ensure_ascii=False), 1000)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter missing message content: {snip}",
        )

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        if ctx:
            logger.debug("[headers][%s] got content (%d chars)", ctx.request_id, len(content))
            _dump_json(
                ctx,
                "openrouter_content_preview.json",
                {"content_preview": _shorten(content)},
            )
        return content.strip()

    # Fallback: try to extract from reasoning (if model returned it)
    extracted = _extract_headers_from_reasoning(message.get("reasoning"), ctx=ctx)
    if isinstance(extracted, str) and extracted:
        if ctx:
            logger.debug(
                "[headers][%s] using reasoning-extracted headers (%d chars)",
                ctx.request_id,
                len(extracted),
            )
        return extracted

    snip = _shorten(json.dumps(payload, ensure_ascii=False), 1000)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"OpenRouter returned empty content (no headers block found). Payload: {snip}",
    )


# ---------------------------
# Public endpoint
# ---------------------------


@router.post("/headers", response_model=list[HeaderItem])
async def extract_openrouter_headers(payload: OpenRouterHeadersRequest) -> List[HeaderItem]:
    """Extract headers for an upload using an OpenRouter-hosted model (with deep diagnostics)."""

    req_id = uuid.uuid4().hex[:8].upper()
    t0 = time.time()

    # Minimal payload introspection (without leaking secrets)
    try:
        api_key = (payload.api_key or "").strip()
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_key is required for OpenRouter",
            )
        redacted_key = api_key[:6] + "…" + api_key[-4:] if len(api_key) >= 12 else "***REDACTED***"

        ctx = DebugCtx(upload_id=payload.upload_id, request_id=req_id, model=payload.model)
        logger.debug(
            "[headers][%s] START upload_id=%s model=%s",
            req_id,
            payload.upload_id,
            payload.model,
        )

        # Document fetch
        t_doc = time.time()
        document = fetch_document_text(payload.upload_id)
        logger.debug(
            "[headers][%s] fetched document (%d chars) in %d ms",
            req_id,
            len(document or ""),
            _time_ms(t_doc),
        )
        _dump_json(
            ctx,
            "document_preview.json",
            {"chars": len(document or ""), "preview": _shorten(document)},
        )

        cleaned_document = clean_document_for_headers(document)
        logger.debug(
            "[headers][%s] cleaned document (%d chars)",
            req_id,
            len(cleaned_document or ""),
        )
        _dump_json(
            ctx,
            "cleaned_document_preview.json",
            {"chars": len(cleaned_document or ""), "preview": _shorten(cleaned_document)},
        )

        # Build messages
        t_msg = time.time()
        messages = build_header_messages(cleaned_document)
        logger.debug(
            "[headers][%s] built messages (%d items) in %d ms",
            req_id,
            len(messages),
            _time_ms(t_msg),
        )
        _dump_json(
            ctx,
            "messages_preview.json",
            {
                "count": len(messages),
                "first_two": [
                    {**m, "content": _shorten(m.get("content", ""))} for m in messages[:2]
                ],
            },
        )

        # Base URL normalize
        base_url = _normalize_openrouter_base_url(payload.base_url, ctx=ctx)
        ctx.base_url = base_url

        # Timeout and params
        params = dict(payload.params or {})
        params.setdefault("temperature", 0)
        params.setdefault("stop", ["#headers_end#"])
        timeout = float(params.get("timeout", 360.0))
        logger.debug(
            "[headers][%s] timeout=%s params_keys=%s api_key=%s",
            req_id,
            timeout,
            list(params.keys()),
            redacted_key,
        )

        # Call OpenRouter
        t_or = time.time()
        response_text = await _chat_via_openrouter(
            base_url=base_url,
            api_key=api_key,
            model=payload.model,
            messages=messages,
            params=params,
            timeout=timeout,
            ctx=ctx,
        )
        logger.debug(
            "[headers][%s] openrouter call returned (%d chars) in %d ms",
            req_id,
            len(response_text or ""),
            _time_ms(t_or),
        )
        _dump_json(
            ctx,
            "model_output_preview.json",
            {"preview": _shorten(response_text)},
        )

        # Parse + store headers
        t_parse = time.time()
        headers_items = parse_and_store_headers(
            payload.upload_id,
            response_text,
            cleaned_document=cleaned_document,
            on_verify=lambda header, _pos, snippet: _dump_evidence(
                ctx, header.section_name, snippet, "body"
            ),
            on_reject=lambda header, snippet: _dump_evidence(
                ctx, header.section_name, snippet, "rejected"
            ),
        )
        logger.debug(
            "[headers][%s] parse_and_store_headers -> %d items in %d ms",
            req_id,
            len(headers_items),
            _time_ms(t_parse),
        )
        _dump_json(
            ctx,
            "parsed_headers.json",
            [h.model_dump() if hasattr(h, "model_dump") else h for h in headers_items],
        )

        logger.debug("[headers][%s] DONE total=%d ms", req_id, _time_ms(t0))
        return headers_items

    except HTTPException:
        # Let FastAPI handle it, but log with request id
        logger.exception("[headers][%s] HTTPException raised", req_id)
        raise
    except Exception as e:  # pragma: no cover - safety net
        logger.exception("[headers][%s] unexpected error: %r", req_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error [{req_id}]: {e!r}",
        )

