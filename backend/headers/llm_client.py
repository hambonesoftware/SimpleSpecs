"""Thin OpenRouter adapter used by the header extractor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Mapping

from backend.services import openrouter_client

from .prompt import Prompt


@dataclass(slots=True)
class LLMResponse:
    """Container describing an LLM completion."""

    text: str
    model: str


class LLMClient:
    """Async wrapper around :mod:`backend.services.openrouter_client`."""

    def __init__(self, *, model: str, timeout_s: int) -> None:
        self.model = model
        self.timeout_s = timeout_s

    async def complete(
        self,
        prompt: Prompt,
        document_text: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> LLMResponse:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]

        response_text = await asyncio.to_thread(
            openrouter_client.chat,
            messages,
            model=self.model,
            temperature=0.0,
            params=params,
            timeout_read=self.timeout_s,
        )
        return LLMResponse(text=response_text, model=self.model)


__all__ = ["LLMClient", "LLMResponse"]
