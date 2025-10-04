"""Base LLM provider abstractions."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, List

from fastapi import HTTPException, status


class LLMProvider(ABC):
    """Abstract chat completion provider."""

    def __init__(self, model: str, params: dict[str, Any] | None = None) -> None:
        self.model = model
        self.params = params or {}

    async def chat(self, messages: List[dict[str, str]]) -> str:
        retries = 3
        delay = 1.5
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return await self._chat(messages)
            except Exception as exc:  # noqa: BLE001 - we re-raise as HTTPException
                last_exc = exc
                if attempt == retries:
                    break
                await asyncio.sleep(delay * attempt)
        message = "LLM request failed"
        if last_exc:
            message = f"LLM request failed: {last_exc}"  # type: ignore[str-format]
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message)

    @abstractmethod
    async def _chat(self, messages: List[dict[str, str]]) -> str:
        raise NotImplementedError


def get_provider(
    provider: str,
    *,
    model: str,
    params: dict[str, Any] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """Factory that returns a configured provider implementation."""

    if provider == "openrouter":
        from .openrouter import OpenRouterProvider

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OpenRouter API key is required",
            )
        return OpenRouterProvider(model=model, params=params, api_key=api_key)
    if provider == "llamacpp":
        from .llamacpp import LlamaCPPProvider

        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="llama.cpp base_url is required",
            )
        return LlamaCPPProvider(model=model, params=params, base_url=base_url)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")
