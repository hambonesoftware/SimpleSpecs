import asyncio

from backend.config import Settings
from backend.services import headers_orchestrator


async def _run_extract(monkeypatch, tmp_path, *, llm_exception: Exception | None = None):
    lines = [
        {
            "text": "Intro",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        }
    ]

    def _fake_collect(*args, **kwargs):  # noqa: ANN001 - test stub
        return lines, set(), "hash-value"

    async def _fake_llm(*args, **kwargs):  # noqa: ANN001 - test stub
        if llm_exception is not None:
            raise llm_exception
        return [
            {"text": "Intro", "number": "1", "level": 1},
        ]

    def _fake_locate(headers, *_args, **_kwargs):  # noqa: ANN001 - test stub
        return [
            {
                "text": headers[0]["text"],
                "number": headers[0]["number"],
                "level": headers[0]["level"],
                "page": 0,
                "line_idx": 0,
                "global_idx": 0,
            }
        ]

    def _fake_chunks(headers, _lines):  # noqa: ANN001 - test stub
        return [
            {
                "header_text": headers[0]["text"],
                "header_number": headers[0]["number"],
                "level": headers[0]["level"],
                "start_global_idx": 0,
                "end_global_idx": 0,
                "start_page": 0,
                "end_page": 0,
            }
        ]

    monkeypatch.setattr(
        "backend.services.headers_orchestrator.collect_line_metrics", _fake_collect
    )
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.get_headers_llm_full", _fake_llm
    )
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.locate_headers_in_lines", _fake_locate
    )
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.single_chunks_from_headers", _fake_chunks
    )

    settings = Settings(upload_dir=tmp_path, headers_mode="llm_full")

    return await headers_orchestrator.extract_headers_and_chunks(
        b"pdf-bytes",
        settings=settings,
        native_headers=[{"text": "Intro", "number": "1", "level": 1}],
        metadata={"filename": "doc.pdf"},
    )


def test_extract_headers_llm_failure_emits_message(monkeypatch, tmp_path) -> None:
    result = asyncio.run(
        _run_extract(
            monkeypatch,
            tmp_path,
            llm_exception=RuntimeError("OpenRouter HTTP 403: Forbidden"),
        )
    )

    assert result["mode"] == "native"
    assert result["messages"]
    assert "HTTP 403" in result["messages"][0]


def test_extract_headers_llm_success_has_no_messages(monkeypatch, tmp_path) -> None:
    result = asyncio.run(_run_extract(monkeypatch, tmp_path))

    assert result["mode"] == "llm_full"
    assert result["messages"] == []
