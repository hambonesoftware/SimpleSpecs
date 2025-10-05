"""llama.cpp / Ollama-compatible chat completion provider (drop-in ready).

Supports:
- OpenAI-compatible llama.cpp server: POST {base_url}/v1/chat/completions -> data["choices"][0]["message"]["content"]
- Ollama-compatible server (or llama.cpp /api/chat): POST {base_url}/api/chat or full URL -> data["message"]["content"]

Usage notes:
- Pass `base_url` as either the server root (e.g. "http://localhost:8080")
  or the full endpoint (e.g. ".../v1/chat/completions" or ".../api/chat").
- `params` can include extra generation options (temperature, top_p, etc.).
  They will be merged into the JSON payload.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from ...logging import get_logger
from .llm_provider import LLMProvider


logger = get_logger(__name__)


class LlamaCPPProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        params: Optional[Dict[str, Any]] = None,
        base_url: str,
        timeout: float = 60.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Create a provider that can talk to either:
          - llama.cpp's OpenAI-compatible server (/v1/chat/completions), or
          - Ollama-style chat endpoint (/api/chat).

        Args:
            model: Model name to use on the server.
            params: Extra generation parameters merged into the request JSON.
            base_url: Server base URL or a full endpoint URL.
            timeout: Request timeout in seconds.
            headers: Optional HTTP headers to include (defaults to JSON content type).
        """
        super().__init__(model=model, params=params)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if headers:
            self.headers.update(headers)

    # ------------------------------ Public API ------------------------------ #

    async def _chat(self, messages: List[Dict[str, str]]) -> str:
        """
        Send chat messages and return the assistant's text content.

        The shape of `messages` is a list of dicts like:
            {"role": "user" | "system" | "assistant", "content": "<text>"}
        """
        url, endpoint_flavor = self._resolve_url(self.base_url)

        # Base payload works for both llama.cpp OpenAI-compatible and Ollama /api/chat.
        # (Ollama also supports "options": {...}, but direct params on root is accepted by many servers.)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        # Merge in any extra parameters (temperature, top_p, max_tokens, etc.)
        if self.params:
            payload.update(self.params)

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            resp = await client.post(url, json=payload)
            logger.info("Header LM raw response (llama.cpp provider): %s", resp.text)
            # Raise detailed HTTP errors early
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Include server response text for debugging clarity
                raise RuntimeError(
                    f"LLM server returned HTTP {resp.status_code} at {url}: {resp.text}"
                ) from e

            data = resp.json()

        content = self._extract_content(data, endpoint_flavor)
        if isinstance(content, str) and content.strip():
            return content.strip()

        raise RuntimeError(f"Unexpected response structure (no content): {data}")

    # ----------------------------- Helper Methods --------------------------- #

    def _resolve_url(self, base_url: str) -> tuple[str, str]:
        """
        Decide which endpoint to call and return (url, flavor).

        flavor ∈ {"openai", "ollama"} to guide response parsing.
        """
        # If the user passed an explicit endpoint, honor it and detect flavor.
        if base_url.endswith("/v1/chat/completions"):
            return base_url, "openai"
        if base_url.endswith("/api/chat"):
            return base_url, "ollama"

        # Otherwise, append a sensible default. Prefer OpenAI-compatible path by default.
        # Many llama.cpp servers expose /v1/chat/completions.
        # Ollama typically uses /api/chat. If user wants Ollama, they can pass that explicitly.
        return f"{base_url}/v1/chat/completions", "openai"

    def _extract_content(self, data: Any, flavor: str) -> Optional[str]:
        """
        Normalize and extract text content from varied server responses.

        - OpenAI-compatible (llama.cpp): data["choices"][0]["message"]["content"]
        - Ollama-style (/api/chat):      data["message"]["content"]

        Also tolerates servers that always return a top-level "message".
        """
        # Primary path depending on detected flavor
        if flavor == "openai":
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                # Fallback in case the server returns a simplified shape
                pass

        if flavor == "ollama":
            try:
                return data["message"]["content"]
            except (KeyError, TypeError):
                # Fallback to OpenAI-compatible shape if needed
                pass

        # Generic fallbacks (be forgiving across servers)
        if isinstance(data, dict):
            # Some servers put the message at top-level "message"
            msg = data.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content

            # Or still might be OpenAI-like but with slight variations
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                choice0 = choices[0]
                if isinstance(choice0, dict):
                    message = choice0.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str):
                            return content

        return None
