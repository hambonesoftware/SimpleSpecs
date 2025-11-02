"""LLM integration layer providing provider abstraction, caching, and retries."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

import httpx

from ..config import Settings
from .openrouter_client import OpenRouterError, chat as openrouter_chat

LOGGER = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Raised when the LLM provider returns an unrecoverable error."""


class LLMRetryableError(LLMProviderError):
    """Raised for retryable provider errors (e.g., rate limits)."""


class LLMCircuitOpenError(LLMProviderError):
    """Raised when the circuit breaker prevents additional calls."""


@dataclass(frozen=True)
class LLMTransportRequest:
    """Container describing a transport request to a provider."""

    model: str
    messages: Sequence[Mapping[str, str]]
    params: Mapping[str, Any]
    headers: Mapping[str, str]
    metadata: Mapping[str, Any] | None = None


@dataclass
class LLMTransportResponse:
    """Response payload returned by a transport implementation."""

    content: str
    usage: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] | None = None


@dataclass
class LLMResult:
    """High-level result returned by :class:`LLMService`."""

    content: str
    usage: Mapping[str, Any] | None
    cached: bool
    fenced: str | None = None


class LLMService:
    """Provide hardened LLM requests with caching, retries, and backoff."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache_dir: Path | None = None,
        transport_overrides: Mapping[
            str, Callable[[LLMTransportRequest], LLMTransportResponse]
        ]
        | None = None,
        sleep: Callable[[float], None] = time.sleep,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._cache_dir = cache_dir or settings.upload_dir / ".llm_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._transports = dict(transport_overrides or {})
        self._sleep = sleep
        self._time = time_func
        self._failure_count = 0
        self._circuit_open_until: float | None = None
        self._max_retries = 2
        self._base_backoff = 1.5
        self._circuit_threshold = 3
        self._cooldown_seconds = 30.0

    @property
    def is_enabled(self) -> bool:
        provider = self.get_provider()
        if provider == "openrouter":
            return bool(self._settings.openrouter_api_key)
        if provider == "ollama":
            return True
        return False

    def get_provider(self) -> str:
        """Return the configured provider identifier."""

        return (self._settings.llm_provider or "openrouter").lower()

    def generate(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        model: str | None = None,
        fence: str | None = None,
        params: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        """Generate a completion with retries, caching, and fence validation."""

        if not messages:
            raise ValueError("LLMService.generate requires at least one message")

        provider = self.get_provider()
        if self._circuit_open_until and self._time() < self._circuit_open_until:
            raise LLMCircuitOpenError(
                f"Provider circuit open for another {self._circuit_open_until - self._time():.1f}s"
            )

        base_model = model or self._settings.openrouter_model
        base_params: MutableMapping[str, Any] = dict(params or {})
        base_params["max_tokens"] = self._ensure_max_tokens(
            base_params.get("max_tokens")
        )

        cache_key = self._build_cache_key(provider, base_model, messages, base_params)
        cached = self._read_cache(cache_key)
        if cached is not None:
            LOGGER.debug("LLM cache hit provider=%s model=%s", provider, base_model)
            fenced_text = (
                self._extract_fence(cached["content"], fence) if fence else None
            )
            if cached.get("usage"):
                self._log_usage(provider, base_model, cached.get("usage"), cached=True)
            self._echo_response(cached["content"])
            return LLMResult(
                content=cached["content"],
                usage=cached.get("usage"),
                cached=True,
                fenced=fenced_text,
            )

        attempt = 0
        preamble_added = False
        last_error: Exception | None = None
        base_messages = [dict(message) for message in messages]

        while attempt <= self._max_retries:
            attempt += 1
            messages_to_send = list(base_messages)
            if preamble_added:
                messages_to_send.insert(
                    0,
                    {
                        "role": "system",
                        "content": f"ONLY FENCED OUTPUT using {fence} fences.",
                    },
                )

            request = LLMTransportRequest(
                model=base_model,
                messages=messages_to_send,
                params=dict(base_params),
                headers=self._build_headers(provider),
                metadata=metadata or {},
            )

            try:
                response = self._call_provider(provider, request)
            except LLMRetryableError as error:
                last_error = error
                self._register_failure()
                if attempt > self._max_retries:
                    break
                self._sleep(self._backoff_seconds(attempt))
                continue
            except LLMProviderError as error:
                last_error = error
                self._register_failure(trip=True)
                break

            self._reset_failures()
            content = response.content
            self._echo_response(content)
            fenced_block = self._extract_fence(content, fence) if fence else None
            if fence and not fenced_block:
                last_error = LLMProviderError("Response missing fenced output")
                if attempt > self._max_retries:
                    self._register_failure(trip=True)
                    break
                preamble_added = True
                continue

            result = {
                "content": content,
                "usage": dict(response.usage or {}),
            }
            self._write_cache(cache_key, result)
            if response.usage:
                self._log_usage(provider, base_model, response.usage, cached=False)
            return LLMResult(
                content=content,
                usage=response.usage,
                cached=False,
                fenced=fenced_block,
            )

        if last_error is None:
            last_error = LLMProviderError("Unknown LLM failure")
        raise last_error

    def _echo_response(self, content: str) -> None:
        """Print the raw LLM response content to standard output."""

        print(content, flush=True)

    def _register_failure(self, *, trip: bool = False) -> None:
        self._failure_count += 1
        if trip or self._failure_count >= self._circuit_threshold:
            self._circuit_open_until = self._time() + self._cooldown_seconds
            LOGGER.warning(
                "LLM circuit opened after %s consecutive failures; cooling down for %.1fs",
                self._failure_count,
                self._cooldown_seconds,
            )
            self._failure_count = 0

    def _reset_failures(self) -> None:
        self._failure_count = 0
        self._circuit_open_until = None

    def _backoff_seconds(self, attempt: int) -> float:
        return self._base_backoff * max(1, attempt)

    def _build_cache_key(
        self,
        provider: str,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        params: Mapping[str, Any],
    ) -> str:
        serialisable = {
            "provider": provider,
            "model": model,
            "messages": list(messages),
            "params": dict(params),
        }
        payload = json.dumps(serialisable, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        cache_path = self._cache_path(cache_key)
        if not cache_path.exists():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - cache corruption
            LOGGER.warning("Failed to read LLM cache %s: %s", cache_path, exc)
            return None

    def _write_cache(self, cache_key: str, payload: Mapping[str, Any]) -> None:
        cache_path = self._cache_path(cache_key)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, cache_path)

    def _build_headers(self, provider: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if provider == "openrouter":
            if not self._settings.openrouter_api_key:
                raise LLMProviderError("OPENROUTER_API_KEY is not configured")
            headers["Authorization"] = f"Bearer {self._settings.openrouter_api_key}"
            if self._settings.openrouter_http_referer:
                headers["HTTP-Referer"] = self._settings.openrouter_http_referer.strip()
            if self._settings.openrouter_title:
                headers["X-Title"] = self._settings.openrouter_title.strip()
        return headers

    def _call_provider(
        self, provider: str, request: LLMTransportRequest
    ) -> LLMTransportResponse:
        if provider in self._transports:
            return self._transports[provider](request)
        if provider == "openrouter":
            return self.call_openrouter(request)
        if provider == "ollama":
            return self.call_ollama(request)
        raise LLMProviderError(f"Unsupported LLM provider: {provider}")

    def call_openrouter(self, request: LLMTransportRequest) -> LLMTransportResponse:
        params = dict(request.params)
        raw_temperature = params.pop("temperature", None)
        try:
            temperature = float(raw_temperature) if raw_temperature is not None else 0.6
        except (TypeError, ValueError):
            temperature = 0.6

        try:
            content = openrouter_chat(
                [dict(message) for message in request.messages],
                model=request.model,
                temperature=temperature,
                params=params,
                headers=request.headers,
            )
        except OpenRouterError as exc:
            status = exc.status_code
            if status in {429, 500, 502, 503, 504}:
                raise LLMRetryableError(
                    f"OpenRouter HTTP {status or 'error'}"
                ) from exc
            raise LLMProviderError(str(exc)) from exc

        return LLMTransportResponse(content=content, usage=None, raw=None)

    def call_ollama(self, request: LLMTransportRequest) -> LLMTransportResponse:
        payload = {
            "model": request.model,
            "messages": list(request.messages),
            "stream": False,
        }
        payload.update(request.params)
        try:
            response = httpx.post(
                "http://127.0.0.1:11434/api/chat",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {408, 429, 500, 502, 503, 504}:
                raise LLMRetryableError(f"Ollama HTTP {status}") from exc
            raise LLMProviderError(f"Ollama HTTP {status}") from exc
        except httpx.RequestError as exc:  # pragma: no cover - network failure
            raise LLMRetryableError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        if "message" in data:
            content = data["message"].get("content", "")
        else:
            content = data.get("content", "")
        usage = data.get("usage")
        return LLMTransportResponse(content=content, usage=usage, raw=data)

    def _extract_fence(self, content: str, fence: str | None) -> str | None:
        if not fence:
            return None
        pattern = re.compile(
            rf"{re.escape(fence)}\s*(.*?)\s*{re.escape(fence)}", re.DOTALL
        )
        match = pattern.search(content)
        if not match:
            return None
        return match.group(1).strip()

    def _ensure_max_tokens(self, value: Any) -> int:
        try:
            numeric = int(value)
        except Exception:
            numeric = 2048
        return max(numeric, 120_000)

    def _log_usage(
        self,
        provider: str,
        model: str,
        usage: Mapping[str, Any] | None,
        *,
        cached: bool,
    ) -> None:
        if not usage:
            return
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        LOGGER.info(
            "LLM usage provider=%s model=%s prompt=%s completion=%s total=%s cached=%s",
            provider,
            model,
            prompt,
            completion,
            total,
            cached,
        )


# Backwards compatibility hook patched in tests; real pipeline uses :class:`LLMService`.
get_outline_for_headers = None  # type: ignore[assignment]


__all__ = [
    "LLMCircuitOpenError",
    "LLMProviderError",
    "LLMResult",
    "LLMRetryableError",
    "LLMService",
    "LLMTransportRequest",
    "LLMTransportResponse",
]
