"""Tests for the llama.cpp provider adapter."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.llm.llamacpp import LlamaCPPProvider


@pytest.fixture
def anyio_backend() -> str:
    """Configure the AnyIO pytest plugin to use asyncio only."""
    return "asyncio"


def _mock_async_client(
    expected_url: str, expected_payload: Dict[str, Any], response_data: Dict[str, Any]
):
    """Create a context manager that mimics httpx.AsyncClient for tests."""

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - test helper
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> "_AsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: dict):
            assert url == expected_url
            assert json == expected_payload
            return httpx.Response(
                status_code=200,
                json=response_data,
                request=httpx.Request("POST", url),
            )

    return _AsyncClient


@pytest.mark.anyio
async def test_llamacpp_provider_parses_openai_like_response(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LlamaCPPProvider(model="llama", params={}, base_url="http://localhost:8080")
    expected_payload = {
        "model": "llama",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
    }
    response_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hi there!",
                }
            }
        ]
    }
    mock_client = _mock_async_client(
        "http://localhost:8080/v1/chat/completions",
        expected_payload,
        response_data,
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    result = await provider._chat([{"role": "user", "content": "Hello"}])

    assert result == "Hi there!"


@pytest.mark.anyio
async def test_llamacpp_provider_supports_ollama_response(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LlamaCPPProvider(
        model="llama2",
        params={"temperature": 0.2},
        base_url="http://localhost:11434/api/chat",
    )
    expected_payload = {
        "model": "llama2",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.2,
        "stream": False,
    }
    response_data = {
        "message": {
            "role": "assistant",
            "content": "Howdy!",
        }
    }
    mock_client = _mock_async_client(
        "http://localhost:11434/api/chat",
        expected_payload,
        response_data,
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    result = await provider._chat([{"role": "user", "content": "Hello"}])

    assert result == "Howdy!"


@pytest.mark.anyio
async def test_llamacpp_provider_raises_on_unknown_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LlamaCPPProvider(model="llama", params={}, base_url="http://localhost:8080")
    mock_client = _mock_async_client(
        "http://localhost:8080/v1/chat/completions",
        {
            "model": "llama",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
        {"unexpected": "payload"},
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    with pytest.raises(RuntimeError):
        await provider._chat([{"role": "user", "content": "Hello"}])
