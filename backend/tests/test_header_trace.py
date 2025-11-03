import asyncio
import json
from pathlib import Path

import backend.config as app_config
from backend.config import Settings
from backend.services import headers_orchestrator
from backend.services.headers_llm_strict import extract_headers_and_sections_strict
from backend.services.pdf_headers_llm_full import LLMFullHeadersResult
from backend.utils.trace import HeaderTracer


def test_header_trace_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_config, "HEADERS_TRACE", True)
    monkeypatch.setattr(app_config, "HEADERS_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_config, "HEADERS_TRACE_EMBED_RESPONSE", False)

    sample_lines = [
        {
            "text": "1 Introduction",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        }
    ]

    def _fake_collect(document_bytes, *_args, tracer=None, **_kwargs):  # noqa: ANN001
        if tracer is not None:
            tracer.log_call("backend.services.pdf_native.collect_line_metrics")
            tracer.ev(
                "pre_normalize_sample",
                page=0,
                line_idx=0,
                text="1 Introduction",
            )
        return sample_lines, set(), "hash-value"

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        tracer = _kwargs.get("tracer")
        if tracer is not None:
            tracer.log_call("backend.services.pdf_headers_llm_full.get_headers_llm_full")
            tracer.ev(
                "llm_request",
                part=1,
                total_parts=1,
                model="stub-model",
                temperature=0.0,
                timeout_read=0,
                params={},
                messages=[{"role": "user", "content": "stub"}],
            )
        return LLMFullHeadersResult(
            headers=[{"text": "Introduction", "number": "1", "level": 1}],
            raw_responses=["raw"],
            fenced_blocks=[
                "-----BEGIN SIMPLEHEADERS JSON-----\n{\"headers\": []}\n-----END SIMPLEHEADERS JSON-----"
            ],
        )

    monkeypatch.setattr(
        "backend.services.headers_orchestrator.collect_line_metrics", _fake_collect
    )
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.get_headers_llm_full", _fake_llm
    )

    settings = Settings(headers_mode="llm_full", upload_dir=tmp_path)
    payload, tracer = asyncio.run(
        headers_orchestrator.extract_headers_and_chunks(
            b"pdf-bytes",
            settings=settings,
            native_headers=[{"text": "Introduction", "number": "1", "level": 1}],
            metadata={},
            want_trace=True,
        )
    )

    assert tracer is not None
    events = tracer.as_list()
    types = {event["type"] for event in events}
    assert "start_run" in types
    assert "end_run" in types
    expected_trace_markers = {
        "candidate_found",
        "anchor_resolved",
        "anchor_candidate_top",
        "anchor_resolved_top",
        "anchor_resolved_child",
    }
    assert types.intersection(expected_trace_markers)
    assert any(event["type"] == "pre_normalize_sample" for event in events)

    trace_path = Path(tracer.path)
    assert trace_path.exists()
    content = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert content
    assert any(
        any(marker in line for marker in expected_trace_markers) for line in content
    )
    assert payload["headers"]

    summary_path = Path(tracer.summary_path)
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["llm_headers"]
    assert summary["llm_requests"]
    assert summary["llm_requests"][0]["messages"][0]["content"] == "stub"
    assert summary["llm_raw_responses"] == ["raw"]
    assert summary["llm_fenced_blocks"] == [
        "-----BEGIN SIMPLEHEADERS JSON-----\n{\"headers\": []}\n-----END SIMPLEHEADERS JSON-----"
    ]
    assert summary["final_outline"]["headers"]
    call_names = [entry["name"] for entry in summary["function_calls"]]
    assert call_names[0] == "backend.services.headers_orchestrator.extract_headers_and_chunks"
    assert (
        call_names.index("backend.services.pdf_native.collect_line_metrics")
        > call_names.index("backend.services.headers_orchestrator.extract_headers_and_chunks")
    )
    assert (
        call_names.index("backend.services.pdf_headers_llm_full.get_headers_llm_full")
        > call_names.index("backend.services.pdf_native.collect_line_metrics")
    )
    assert (
        call_names.index("backend.services.header_locator.locate_headers_in_lines")
        > call_names.index("backend.services.pdf_headers_llm_full.get_headers_llm_full")
    )
    assert "backend.services.headers_sequential.align_headers_sequential" in call_names
    assert (
        call_names.index("backend.services.headers_orchestrator._enforce_header_sequence")
        > call_names.index("backend.services.header_locator.locate_headers_in_lines")
    )


def test_header_trace_summary_created_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_config, "HEADERS_TRACE", False)
    monkeypatch.setattr(app_config, "HEADERS_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_config, "HEADERS_TRACE_EMBED_RESPONSE", False)

    sample_lines = [
        {
            "text": "1 Intro",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
        }
    ]

    def _fake_collect(document_bytes, *_args, tracer=None, **_kwargs):  # noqa: ANN001
        if tracer is not None:
            tracer.log_call("backend.services.pdf_native.collect_line_metrics")
            tracer.ev(
                "pre_normalize_sample",
                page=0,
                line_idx=0,
                text="1 Intro",
            )
        return sample_lines, set(), "hash-value"

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        tracer = _kwargs.get("tracer")
        if tracer is not None:
            tracer.log_call("backend.services.pdf_headers_llm_full.get_headers_llm_full")
            tracer.ev(
                "llm_request",
                part=1,
                total_parts=1,
                model="stub-model",
                temperature=0.0,
                timeout_read=0,
                params={},
                messages=[{"role": "user", "content": "stub"}],
            )
        return LLMFullHeadersResult(
            headers=[{"text": "Intro", "number": "1", "level": 1}],
            raw_responses=["raw"],
            fenced_blocks=[
                "-----BEGIN SIMPLEHEADERS JSON-----\n{\"headers\": []}\n-----END SIMPLEHEADERS JSON-----"
            ],
        )

    monkeypatch.setattr(
        "backend.services.headers_orchestrator.collect_line_metrics", _fake_collect
    )
    monkeypatch.setattr(
        "backend.services.headers_orchestrator.get_headers_llm_full", _fake_llm
    )

    settings = Settings(headers_mode="llm_full", upload_dir=tmp_path)
    payload, tracer = asyncio.run(
        headers_orchestrator.extract_headers_and_chunks(
            b"pdf-bytes",
            settings=settings,
            native_headers=[{"text": "Intro", "number": "1", "level": 1}],
            metadata={},
        )
    )

    assert tracer is not None
    summary_path = Path(tracer.summary_path)
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["llm_headers"][0]["text"] == "Intro"
    assert summary["llm_requests"]
    assert summary["llm_requests"][0]["messages"][0]["content"] == "stub"
    assert summary["llm_raw_responses"] == ["raw"]
    assert summary["llm_fenced_blocks"] == [
        "-----BEGIN SIMPLEHEADERS JSON-----\n{\"headers\": []}\n-----END SIMPLEHEADERS JSON-----"
    ]
    assert summary["final_outline"]["headers"][0]["text"] == "Intro"
    call_names = [entry["name"] for entry in summary["function_calls"]]
    assert call_names[0] == "backend.services.headers_orchestrator.extract_headers_and_chunks"
    assert "backend.services.header_locator.locate_headers_in_lines" in call_names
    assert payload["headers"]


def test_header_trace_events_emitted_for_strict_mode(tmp_path) -> None:
    tracer = HeaderTracer(out_dir=str(tmp_path))

    class _FakeLLM:
        def generate(self, *, messages, fence, params=None, metadata=None):  # noqa: ANN001, D401
            class _Result:
                def __init__(self) -> None:
                    self.fenced = json.dumps(
                        {
                            "headers": [
                                {"text": "1 Introduction", "number": "1", "level": 1}
                            ]
                        }
                    )

            return _Result()

    lines = [
        {
            "text": "1 Introduction",
            "page": 0,
            "line_idx": 0,
            "global_idx": 0,
            "is_running": False,
            "is_toc": False,
            "is_index": False,
        }
    ]

    output = extract_headers_and_sections_strict(
        llm=_FakeLLM(),
        lines=lines,
        tracer=tracer,
    )

    assert output["headers"]
    tracer.flush_jsonl()
    events = tracer.as_list()
    event_types = {event["type"] for event in events}
    assert "llm_outline_received" in event_types
    assert "candidate_found" in event_types
