from __future__ import annotations

import asyncio
import pytest

from backend.headers.extract_headers import HeadersConfig, extract_headers
from backend.headers.llm_client import LLMResponse
from backend.services.openrouter_client import OpenRouterError
from pathlib import Path


class ScriptedLLM:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.model = "stub"

    async def complete(self, prompt, document_text: str, *, params=None):
        if not self._responses:
            raise AssertionError("Scripted client exhausted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(text=response, model="stub")


def test_attempt_summaries_capture_failure_reasons() -> None:
    config = HeadersConfig(
        model="primary",
        fallback_model="backup",
        timeout_s=1,
        max_input_tokens=1024,
        cache_dir=Path(".cache/test"),
        chunking="force",
        chunk_target_tokens=500,
        retry_max=0,
        backoff_s=0,
        suppress_toc=False,
        suppress_running=False,
        normalize_confusables=True,
        strict_invariants=True,
        title_only_reanchor=True,
    )

    primary = ScriptedLLM(
        [
            OpenRouterError("timeout", status_code=504),
            "```WRONG\n[]\n```",
            "```SIMPLEHEADERS\nnot json\n```",
        ]
    )
    fallback = ScriptedLLM(["ABORT"])

    result = asyncio.run(
        extract_headers(
            ["Page"],
            config=config,
            llm_client=primary,
            fallback_client=fallback,
            legacy_locator=lambda pages: [],
        )
    )
    reasons_run_one = [attempt.reason for attempt in result.attempts if attempt.reason]

    result_two = asyncio.run(
        extract_headers(
            ["Page"],
            config=config,
            llm_client=ScriptedLLM(
                ["text without fence", "```WRONG\n[]\n```", "```SIMPLEHEADERS\nnot json\n```"]
            ),
            fallback_client=None,
            legacy_locator=lambda pages: [],
        )
    )
    reasons_run_two = [attempt.reason for attempt in result_two.attempts if attempt.reason]

    combined = reasons_run_one + reasons_run_two
    assert {"timeout", "bad_label", "invalid_json", "abort_token", "missing_fence", "empty"}.issubset(
        set(filter(None, combined))
    )
