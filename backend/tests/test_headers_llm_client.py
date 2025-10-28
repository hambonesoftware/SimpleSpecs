from __future__ import annotations

import pytest

from backend.config import Settings
from backend.services.headers import HeadersLLMClient, extract_headers
from backend.services.openrouter_client import OpenRouterError
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult


def _sample_parse_result() -> ParseResult:
    block = ParsedBlock(
        text="1 Scope",
        bbox=(0.0, 0.0, 10.0, 10.0),
        font="Helvetica",
        font_size=12.0,
    )
    page = ParsedPage(page_number=1, width=612.0, height=792.0, blocks=[block])
    return ParseResult(pages=[page])
def test_llm_client_parses_json_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    captured_messages: list[list[dict]] = []

    def fake_chat(messages, **_: object) -> str:
        captured_messages.append(messages)
        return "Here you go {\"headers\": [{\"title\": \"Scope\", \"number\": \"1\", \"level\": 1}]}"

    settings = Settings(upload_dir=tmp_path)
    client = HeadersLLMClient(settings, chat_func=fake_chat)

    result = client.refine_outline(_sample_parse_result())

    assert result is not None
    assert result.outline[0].title == "Scope"
    assert result.outline[0].numbering == "1"
    assert result.fenced_text.splitlines()[0] == "#headers#"
    assert result.fenced_text.splitlines()[-1] == "#/headers#"
    assert captured_messages and len(captured_messages[0]) == 1


def test_extract_headers_includes_message_on_openrouter_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingClient:
        is_enabled = True

        def refine_outline(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise OpenRouterError("403 Forbidden", status_code=403)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    settings = Settings(upload_dir=tmp_path)
    result = extract_headers(
        _sample_parse_result(),
        settings=settings,
        llm_client=FailingClient(),
    )

    assert result.source == "openrouter"
    assert any("403" in message for message in result.messages)
