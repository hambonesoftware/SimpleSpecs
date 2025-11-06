from __future__ import annotations

import pytest

from backend.headers.extract_headers import HeadersConfig, extract_headers
from backend.headers.llm_client import LLMResponse
from backend.headers.models import HeaderItem
from backend.services.openrouter_client import OpenRouterError
import asyncio
from pathlib import Path


class CyclingStubLLM:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.model = "stub"

    async def complete(self, prompt, document_text: str, *, params=None):
        if not self._responses:
            raise AssertionError("Stub exhausted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(text=response, model="stub")


def test_retry_ladder_hits_fallback_model() -> None:
    payload = "```SIMPLEHEADERS\n[{\"title\": \"Scope\", \"number\": \"1\", \"level\": 1, \"page\": 1}]\n```"
    primary = CyclingStubLLM(
        [
            OpenRouterError("timeout", status_code=504),
            "not a fence",
            "```SIMPLEHEADERS\nnot json\n```",
        ]
    )
    fallback = CyclingStubLLM([payload])
    config = HeadersConfig(
        model="primary",
        fallback_model="fallback",
        timeout_s=1,
        max_input_tokens=1024,
        cache_dir=Path(".cache/test"),
        chunking="force",
        chunk_target_tokens=1000,
        retry_max=0,
        backoff_s=0,
        suppress_toc=False,
        suppress_running=False,
        normalize_confusables=True,
        strict_invariants=True,
        title_only_reanchor=True,
    )
    result = asyncio.run(
        extract_headers(
            ["Section 1 Scope"],
            config=config,
            llm_client=primary,
            fallback_client=fallback,
            legacy_locator=lambda pages: [],
        )
    )
    assert result.ok
    reasons = [attempt.reason for attempt in result.attempts if attempt.reason]
    assert reasons[:3] == ["timeout", "missing_fence", "invalid_json"]
    assert result.headers[0].title == "Scope"


def test_legacy_locator_used_after_all_failures() -> None:
    primary = CyclingStubLLM(["not a fence", "```WRONG\n[]\n```"])
    legacy_headers = [HeaderItem(number="1", title="Legacy Scope", level=1, page=1, order=0)]
    config = HeadersConfig(
        model="primary",
        fallback_model="",
        timeout_s=1,
        max_input_tokens=1024,
        cache_dir=Path(".cache/test"),
        chunking="off",
        chunk_target_tokens=1000,
        retry_max=0,
        backoff_s=0,
        suppress_toc=False,
        suppress_running=False,
        normalize_confusables=True,
        strict_invariants=True,
        title_only_reanchor=True,
    )
    result = asyncio.run(
        extract_headers(
            ["Section 1"],
            config=config,
            llm_client=primary,
            fallback_client=None,
            legacy_locator=lambda pages: legacy_headers,
        )
    )
    assert result.ok
    assert result.attempts[-1].rung == "fallback_legacy"
    assert result.headers[0].title == "Legacy Scope"
