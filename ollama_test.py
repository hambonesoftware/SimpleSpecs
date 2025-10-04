"""Quick utility script for interacting with a local Ollama instance."""
from __future__ import annotations

from dataclasses import dataclass

try:  # pragma: no cover - optional dependency for local tooling
    import requests
except ModuleNotFoundError:  # pragma: no cover - graceful import for test collection
    requests = None  # type: ignore[assignment]


@dataclass(frozen=True)
class OllamaConfig:
    """Lightweight configuration for Ollama chat queries."""

    api_url: str = "http://AA-248:11434/api/chat"
    model: str = "llama3.2"
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:  # pragma: no cover - trivial setter
        if self.headers is None:
            object.__setattr__(self, "headers", {"Content-Type": "application/json"})


def query_ollama(prompt: str, config: OllamaConfig | None = None) -> str:
    """Send a single-turn chat message to Ollama and return the response text."""

    if requests is None:  # pragma: no cover - dependency not installed in CI
        raise RuntimeError("The 'requests' package is required to query Ollama.")

    cfg = config or OllamaConfig()
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    response = requests.post(cfg.api_url, json=payload, headers=cfg.headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    message = data.get("message", {})
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    raise RuntimeError("Unexpected response payload from Ollama")


if __name__ == "__main__":  # pragma: no cover - manual utility
    print(query_ollama("Tell me a random dad joke."))
