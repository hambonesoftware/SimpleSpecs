"""Tests for the OpenRouter LLM provider."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.llm.openrouter import OpenRouterProvider


@pytest.fixture
def anyio_backend() -> str:
    """Configure pytest-anyio to use asyncio."""

    return "asyncio"


def _mock_async_client(
    expected_url: str,
    expected_payload: Dict[str, Any],
    expected_headers: Dict[str, str],
    response_data: Dict[str, Any],
):
    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - test helper
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> "_AsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: dict, headers: Dict[str, str]):
            assert url == expected_url
            assert json == expected_payload
            assert headers.get("Authorization") == expected_headers["Authorization"]
            assert headers.get("Content-Type") == expected_headers["Content-Type"]
            return httpx.Response(
                status_code=200,
                json=response_data,
                request=httpx.Request("POST", url),
            )

    return _AsyncClient


@pytest.mark.anyio
async def test_openrouter_provider_uses_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterProvider(
        model="gpt-4",
        params={},
        api_key="secret",
        base_url=None,
    )
    expected_payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response_data = {
        "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
    }
    mock_client = _mock_async_client(
        "https://openrouter.ai/api/v1/chat/completions",
        expected_payload,
        {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
        response_data,
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    result = await provider._chat([{"role": "user", "content": "Hello"}])

    assert result == "Hi"


@pytest.mark.anyio
async def test_openrouter_provider_respects_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterProvider(
        model="spec-model",
        params={"temperature": 0.2},
        api_key="secret",
        base_url="https://router.example/api/v1",
    )
    expected_payload = {
        "model": "spec-model",
        "messages": [{"role": "user", "content": "Ping"}],
        "temperature": 0.2,
    }
    response_data = {
        "choices": [
            {"message": {"role": "assistant", "content": "Pong"}},
        ],
    }
    mock_client = _mock_async_client(
        "https://router.example/api/v1/chat/completions",
        expected_payload,
        {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
        response_data,
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    result = await provider._chat([{"role": "user", "content": "Ping"}])

    assert result == "Pong"


@pytest.mark.anyio
async def test_openrouter_provider_accepts_base_url_without_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenRouterProvider(
        model="spec-model",
        params={},
        api_key="secret",
        base_url="router.example/api/v1",
    )
    response_data = {
        "choices": [
            {"message": {"role": "assistant", "content": "Response"}},
        ],
    }
    mock_client = _mock_async_client(
        "https://router.example/api/v1/chat/completions",
        {
            "model": "spec-model",
            "messages": [{"role": "user", "content": "Hi"}],
        },
        {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        },
        response_data,
    )
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    result = await provider._chat([{"role": "user", "content": "Hi"}])

    assert result == "Response"


def test_openrouter_provider_rejects_invalid_base_url() -> None:
    with pytest.raises(HTTPException):
        OpenRouterProvider(
            model="spec-model",
            params={},
            api_key="secret",
            base_url="http://",
        )

