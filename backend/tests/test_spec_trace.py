"""Tests for the spec trace utilities."""

from __future__ import annotations

import json
from pathlib import Path

from backend.utils.spec_trace import SpecTracer


def test_spec_tracer_serialises_path(tmp_path) -> None:
    out_dir = tmp_path / "traces"
    sample_path = Path("/tmp/example.txt")

    tracer = SpecTracer(out_dir=str(out_dir))
    tracer.metadata(sample=sample_path)

    output_path = Path(tracer.flush())

    assert output_path.exists()

    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["metadata"]["sample"] == str(sample_path)

    metadata_events = [event for event in content["events"] if event["type"] == "metadata"]
    assert metadata_events, "metadata event should be recorded"
    assert metadata_events[0]["sample"] == str(sample_path)
