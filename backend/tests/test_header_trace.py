import asyncio
import json
from pathlib import Path

import backend.config as app_config
from backend.config import Settings
from backend.services import headers_orchestrator


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
            tracer.ev(
                "pre_normalize_sample",
                page=0,
                line_idx=0,
                text="1 Introduction",
            )
        return sample_lines, set(), "hash-value"

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        return [{"text": "Introduction", "number": "1", "level": 1}]

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
    assert "candidate_found" in types or "anchor_resolved" in types
    assert any(event["type"] == "pre_normalize_sample" for event in events)

    trace_path = Path(tracer.path)
    assert trace_path.exists()
    content = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert content
    assert any("candidate_found" in line for line in content)
    assert payload["headers"]

    summary_path = Path(tracer.summary_path)
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["llm_headers"]
    assert summary["final_outline"]["headers"]


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
            tracer.ev(
                "pre_normalize_sample",
                page=0,
                line_idx=0,
                text="1 Intro",
            )
        return sample_lines, set(), "hash-value"

    async def _fake_llm(*_args, **_kwargs):  # noqa: ANN001
        return [{"text": "Intro", "number": "1", "level": 1}]

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
    assert summary["final_outline"]["headers"][0]["text"] == "Intro"
    assert payload["headers"]
