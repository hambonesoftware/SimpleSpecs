import asyncio

from backend.config import Settings
from backend.services import headers_orchestrator
from backend.services.pdf_headers_llm_full import LLMFullHeadersResult


async def _run_extract(
    monkeypatch,
    tmp_path,
    *,
    llm_exception: Exception | None = None,
    strict_mode: bool = False,
):
    lines = [
        {
            "text": "Intro",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        }
    ]

    def _fake_collect(*args, tracer=None, **kwargs):  # noqa: ANN001 - test stub
        if tracer is not None:
            tracer.ev(
                "doc_stats",
                pages=1,
                lines=len(lines),
                bytes=len(args[0]) if args else 0,
                excluded_pages=[],
            )
        return lines, set(), "hash-value"

    async def _fake_llm(*args, **kwargs):  # noqa: ANN001 - test stub
        if llm_exception is not None:
            raise llm_exception
        return LLMFullHeadersResult(
            headers=[{"text": "Intro", "number": "1", "level": 1}],
            raw_responses=["raw-response"],
            fenced_blocks=[
                "-----BEGIN SIMPLEHEADERS JSON-----\n{\"headers\": []}\n-----END SIMPLEHEADERS JSON-----"
            ],
        )

    def _fake_locate(headers, *_args, tracer=None, **_kwargs):  # noqa: ANN001 - test stub
        if tracer is not None:
            tracer.ev(
                "candidate_found",
                target=headers[0]["text"] if headers else "",
                page=0,
                line_idx=0,
                snippet=headers[0]["text"] if headers else "",
                score=1.0,
                before_prev_anchor=False,
            )
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
        if not headers:
            return []
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
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.align_headers_llm_strict",
        lambda headers, _lines, tracer=None: [
            {
                "header": {
                    "text": header.get("text"),
                    "number": header.get("number"),
                    "level": header.get("level"),
                    "_orig_index": idx,
                },
                "line": {
                    "page": 0,
                    "line_idx": 0,
                    "global_idx": idx,
                },
                "score": 1.0,
                "strategy": "unit-test",
                "band": False,
            }
            for idx, header in enumerate(headers)
        ],
    )

    settings = Settings(
        upload_dir=tmp_path, headers_mode="llm_full", headers_llm_strict=strict_mode
    )

    result, _ = await headers_orchestrator.extract_headers_and_chunks(
        b"pdf-bytes",
        settings=settings,
        native_headers=[{"text": "Intro", "number": "1", "level": 1}],
        metadata={"filename": "doc.pdf"},
    )
    return result


def test_extract_headers_llm_failure_emits_message(monkeypatch, tmp_path) -> None:
    result = asyncio.run(
        _run_extract(
            monkeypatch,
            tmp_path,
            llm_exception=RuntimeError("OpenRouter HTTP 403: Forbidden"),
        )
    )

    assert result["mode"] == "llm_full_error"
    assert result["messages"]
    assert "HTTP 403" in result["messages"][0]


def test_extract_headers_llm_success_has_no_messages(monkeypatch, tmp_path) -> None:
    result = asyncio.run(_run_extract(monkeypatch, tmp_path))

    assert result["mode"] == "llm_full"
    assert result["messages"] == []
    assert result["fenced_text"]


def test_extract_headers_strict_mode(monkeypatch, tmp_path) -> None:
    result = asyncio.run(_run_extract(monkeypatch, tmp_path, strict_mode=True))

    assert result["mode"] == "llm_strict"
    assert result["messages"] == []
    assert result["fenced_text"]
