from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.headers.extract_headers import HeadersConfig, extract_headers
from backend.headers.llm_client import LLMResponse
from backend.headers.validators import (
    detect_bad_label,
    extract_fenced_simpleheaders_block,
    parse_fenced_payload,
)


class StubLLMClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.calls: list[str] = []
        self.model = "stub"

    async def complete(self, prompt, document_text: str, *, params=None):
        self.calls.append(prompt.label)
        if not self._responses:
            raise AssertionError("No stub responses left")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(text=response, model="stub")


@pytest.mark.parametrize(
    "payload",
    [
        "no fences",
        "```JSON\n[]\n```\n```JSON\n[]\n```",
    ],
)
def test_extract_fenced_simpleheaders_block_rejects_invalid(payload: str) -> None:
    assert extract_fenced_simpleheaders_block(payload) is None


def test_detect_bad_label_handles_non_simpleheaders() -> None:
    assert detect_bad_label("```WRONG\n[]\n```") is True
    assert detect_bad_label("```SIMPLEHEADERS\n[]\n```") is False


@pytest.mark.parametrize(
    "payload",
    [
        "```SIMPLEHEADERS\n{}\n```",
        "```SIMPLEHEADERS\n[{\"title\":1}]\n```",
    ],
)
def test_parse_fenced_payload_invalid_schema(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_fenced_payload(payload)


def test_abort_response_advances_to_next_rung() -> None:
    payload = "```SIMPLEHEADERS\n[{\"title\": \"Scope\", \"number\": \"1\", \"level\": 1, \"page\": 1}]\n```"
    client = StubLLMClient(["ABORT", payload])
    config = HeadersConfig(
        model="primary",
        fallback_model="fallback",
        timeout_s=1,
        max_input_tokens=2048,
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
    legacy_headers: list = []

    result = asyncio.run(
        extract_headers(
            ["Page 1 title"],
            config=config,
            llm_client=client,
            legacy_locator=lambda pages: legacy_headers,
        )
    )

    assert result.ok
    assert [attempt.reason for attempt in result.attempts[:1]] == ["abort_token"]
    assert result.headers[0].title == "Scope"
