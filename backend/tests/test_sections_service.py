"""Unit tests for section span helpers."""

from __future__ import annotations

from backend.services.sections import build_section_spans


def test_build_section_spans_prefers_last_occurrence() -> None:
    """The span builder should ignore early TOC duplicates."""

    lines = [
        {"global_idx": 5, "text": "1 PRINCIPLES", "page": 0, "line_idx": 0},
        {"global_idx": 50, "text": "1 PRINCIPLES", "page": 2, "line_idx": 1},
        {"global_idx": 55, "text": "Body text", "page": 2, "line_idx": 2},
        {"global_idx": 60, "text": "1.1 Diverter", "page": 2, "line_idx": 3},
        {"global_idx": 70, "text": "Content", "page": 3, "line_idx": 4},
    ]

    simpleheaders = [
        {"text": "PRINCIPLES", "number": "1", "level": 1, "global_idx": 5, "page": 0, "line_idx": 0},
        {"text": "PRINCIPLES", "number": "1", "level": 1, "global_idx": 50, "page": 2, "line_idx": 1},
        {"text": "Diverter", "number": "1.1", "level": 2, "global_idx": 60, "page": 2, "line_idx": 3},
    ]

    spans = build_section_spans(simpleheaders, lines)
    assert len(spans) == 2

    top = spans[0]
    assert top["start_global_idx"] == 50
    assert top["end_global_idx"] == 60
    assert top["section_key"].endswith("::50")

    child = spans[1]
    assert child["start_global_idx"] == 60
    assert child["end_global_idx"] == 71  # last line gid + 1
    assert child["section_key"].endswith("::60")

