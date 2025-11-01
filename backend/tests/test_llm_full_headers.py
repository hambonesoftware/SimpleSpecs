import asyncio
import json

from backend.config import Settings
from backend.services.header_locator import locate_headers_in_lines
from backend.services.pdf_headers_llm_full import get_headers_llm_full
from backend.services.section_chunking import single_chunks_from_headers


def test_locate_headers_prefers_last_match_and_skips_excluded() -> None:
    headers = [{"text": "Overview", "number": None, "level": 1}]
    lines = [
        {
            "text": "Overview",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        },
        {
            "text": "Overview",
            "page": 1,
            "line_idx": 5,
            "global_idx": 5,
            "is_running": True,
        },
        {
            "text": "Overview",
            "page": 2,
            "line_idx": 3,
            "global_idx": 8,
            "is_running": False,
        },
    ]

    located = locate_headers_in_lines(
        headers,
        lines,
        excluded_pages={0},
    )

    assert len(located) == 1
    assert located[0]["global_idx"] == 8
    assert located[0]["page"] == 2


def test_single_chunks_from_headers_produces_ranges() -> None:
    headers = [
        {"text": "Intro", "number": "1", "level": 1, "global_idx": 0},
        {"text": "Details", "number": "1.1", "level": 2, "global_idx": 2},
    ]
    lines = [
        {"global_idx": 0, "page": 0},
        {"global_idx": 1, "page": 0},
        {"global_idx": 2, "page": 0},
        {"global_idx": 3, "page": 1},
    ]

    chunks = single_chunks_from_headers(headers, lines)
    assert len(chunks) == 2
    assert chunks[0]["start_global_idx"] == 0
    assert chunks[0]["end_global_idx"] == 1
    assert chunks[1]["start_global_idx"] == 2
    assert chunks[1]["end_global_idx"] == 3


def test_single_chunks_from_headers_avoids_overlap() -> None:
    headers = [
        {"text": "Overview", "number": "1", "level": 1, "global_idx": 10},
        {"text": "Scope", "number": "1.1", "level": 2, "global_idx": 20},
    ]
    lines = [
        {"global_idx": 10, "page": 0, "text": "Overview"},
        {"global_idx": 11, "page": 0, "text": "Intro text"},
        {"global_idx": 20, "page": 1, "text": "Scope heading"},
        {"global_idx": 21, "page": 1, "text": "Scope body"},
        {"global_idx": 20, "page": 1, "text": "Scope heading duplicate"},
        {"global_idx": 22, "page": 1, "text": "More scope"},
    ]

    chunks = single_chunks_from_headers(headers, lines)

    assert len(chunks) == 2
    assert chunks[0]["end_global_idx"] == 11
    assert chunks[1]["start_global_idx"] == 20


def test_get_headers_llm_full_uses_cache(monkeypatch, tmp_path) -> None:
    calls = 0

    def _fake_chat(messages, **kwargs):  # noqa: ANN001 - test stub
        nonlocal calls
        calls += 1
        payload = {
            "headers": [
                {"text": "Alpha", "number": None, "level": 1},
                {"text": "Beta", "number": "1.1", "level": 2},
            ]
        }
        return (
            "stub\n"
            "-----BEGIN SIMPLEHEADERS JSON-----\n"
            f"{json.dumps(payload)}\n"
            "-----END SIMPLEHEADERS JSON-----"
        )

    monkeypatch.setattr("backend.services.pdf_headers_llm_full.chat", _fake_chat)

    settings = Settings(
        upload_dir=tmp_path,
        headers_llm_cache_dir=tmp_path / "cache",
        headers_llm_model="test-model",
        headers_llm_timeout_s=5,
        openrouter_api_key="sk-test",
    )

    lines = [
        {
            "text": "Alpha",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        }
    ]

    async def _run() -> None:
        result = await get_headers_llm_full(
            lines,
            "hash-value",
            settings=settings,
            excluded_pages=set(),
        )

        assert result.headers[0]["text"] == "Alpha"
        assert result.fenced_blocks
        assert result.raw_responses

        cached_result = await get_headers_llm_full(
            lines,
            "hash-value",
            settings=settings,
            excluded_pages=set(),
        )

        assert calls == 1
        assert cached_result.headers == result.headers

    asyncio.run(_run())
