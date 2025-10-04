"""LLM client abstractions for SimpleSpecs (Phase P0 stubs)."""
from __future__ import annotations

from typing import Protocol

__all__ = ["LLMAdapter", "OpenRouterAdapter", "LlamaCppAdapter"]


class LLMAdapter(Protocol):
    """Protocol describing minimal synchronous LLM interaction."""

    def generate(self, prompt: str) -> str:
        """Generate a response for the given prompt."""


class OpenRouterAdapter:
    """Stub adapter representing an OpenRouter-based integration."""

    def generate(self, prompt: str) -> str:
        return ""


class LlamaCppAdapter:
    """Stub adapter representing a local LLaMA.cpp integration."""

    def generate(self, prompt: str) -> str:
        return ""


def get_llm_client() -> LLMAdapter:
    """Return the default stubbed adapter."""

    return OpenRouterAdapter()
