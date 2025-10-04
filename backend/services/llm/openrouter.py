"""OpenRouter chat completion provider."""
from __future__ import annotations

from typing import Any, List

import httpx

from ...openrouter import normalize_openrouter_base_url
from .llm_provider import LLMProvider


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
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:  # noqa: PERF203 - explicit handling
            raise RuntimeError(f"Unexpected response structure: {data}") from exc
