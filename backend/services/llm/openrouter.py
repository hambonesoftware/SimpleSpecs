"""OpenRouter chat completion provider."""
from __future__ import annotations

from typing import Any, List

import httpx

from .llm_provider import LLMProvider


class OpenRouterProvider(LLMProvider):
    def __init__(self, *, model: str, params: dict[str, Any] | None, api_key: str) -> None:
        super().__init__(model=model, params=params)
        self.api_key = api_key
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"

    async def _chat(self, messages: List[dict[str, str]]) -> str:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        payload.update(self.params)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:  # noqa: PERF203 - explicit handling
            raise RuntimeError(f"Unexpected response structure: {data}") from exc
