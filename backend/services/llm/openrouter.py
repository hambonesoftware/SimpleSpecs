"""OpenRouter chat completion provider."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, List

import httpx

from ...openrouter import normalize_openrouter_base_url
from .llm_provider import LLMProvider

_MAX_CONCURRENT_REQUESTS = 10
_REQUEST_SPACING_SECONDS = 3.0


class _OpenRouterRateLimiter:
    """Coordinate OpenRouter calls to honor concurrency and pacing limits."""

    def __init__(
        self,
        *,
        max_concurrent: int = _MAX_CONCURRENT_REQUESTS,
        spacing_seconds: float = _REQUEST_SPACING_SECONDS,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._next_available: float = 0.0
        self._spacing = spacing_seconds

    @asynccontextmanager
    async def slot(self) -> None:
        """Yield when a request can start respecting limits."""

        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            wait_until = max(now, self._next_available)
            self._next_available = wait_until + self._spacing
        delay = wait_until - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


_OPENROUTER_RATE_LIMITER = _OpenRouterRateLimiter()


class OpenRouterProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        params: dict[str, Any] | None,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        super().__init__(model=model, params=params)
        self.api_key = api_key
        normalized_base_url = normalize_openrouter_base_url(base_url)
        endpoint = normalized_base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        self.base_url = normalized_base_url
        self.endpoint = endpoint

    async def _chat(self, messages: List[dict[str, str]]) -> str:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        payload.update(self.params)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with _OPENROUTER_RATE_LIMITER.slot():
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.endpoint, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:  # noqa: PERF203 - explicit handling
            raise RuntimeError(f"Unexpected response structure: {data}") from exc
