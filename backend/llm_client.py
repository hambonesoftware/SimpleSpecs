"""Minimal LLM client abstraction used by the spec-search pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


@dataclass
class LLMRequest:
    """Parameters for an LLM completion call."""

    model: str
    system_prompt: str
    user_prompt: str
    timeout: int
    max_tokens: int


Transport = Callable[[LLMRequest], Awaitable[str]]


class LLMClient:
    """Simple, awaitable LLM client wrapper."""

    def __init__(self, transport: Optional[Transport] = None) -> None:
        self._transport = transport or self._default_transport

    async def complete(self, request: LLMRequest) -> str:
        """Execute the request using the configured transport."""

        return await self._transport(request)

    async def _default_transport(self, request: LLMRequest) -> str:  # pragma: no cover - guidance
        """Default transport raises to signal missing integration."""

        raise RuntimeError(
            "No LLM transport configured. Provide a transport implementation when "
            "constructing LLMClient."
        )


def create_default_client() -> LLMClient:
    """Factory returning an ``LLMClient`` with the default transport."""

    return LLMClient()
