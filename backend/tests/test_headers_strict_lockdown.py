from __future__ import annotations

from backend.services.headers_llm_strict import (
    align_headers_llm_strict,
    normalize_strict_text,
)


def test_number_normalization_variants() -> None:
    assert normalize_strict_text("1 .I Scope").startswith("1.1")
    assert normalize_strict_text("2 \u00A0.\u2009 1 . 3 Title").startswith("2.1.3")


def test_toc_gating_and_last_occurrence() -> None:
    llm_headers = [
        {"text": "4.1 Requirements", "number": "4.1", "level": 2},
        {"text": "4.2 Deliverables", "number": "4.2", "level": 2},
    ]

    sample_lines = [
        {
            "text": "TABLE OF CONTENTS",
            "global_idx": 0,
            "page": 0,
            "line_idx": 0,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "1 GENERAL ............ 1",
            "global_idx": 1,
            "page": 0,
            "line_idx": 1,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "2 SCOPE .............. 3",
            "global_idx": 2,
            "page": 0,
            "line_idx": 2,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "3 SCHEDULE ........... 5",
            "global_idx": 3,
            "page": 0,
            "line_idx": 3,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "4.1 REQUIREMENTS ..... 8",
            "global_idx": 4,
            "page": 0,
            "line_idx": 4,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "4.2 DELIVERABLES ..... 9",
            "global_idx": 5,
            "page": 0,
            "line_idx": 5,
            "is_toc": True,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "4.1 REQUIREMENTS",
            "global_idx": 100,
            "page": 5,
            "line_idx": 6,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "Body text",
            "global_idx": 101,
            "page": 5,
            "line_idx": 7,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
        {
            "text": "4.2 DELIVERABLES",
            "global_idx": 120,
            "page": 5,
            "line_idx": 8,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        },
    ]

    aligned = align_headers_llm_strict(llm_headers, sample_lines, tracer=None)
    assert aligned, "expected headers to resolve"

    pages = {item["header"]["number"]: item["line"]["page"] for item in aligned}
    assert pages["4.1"] == 5
    assert pages["4.2"] == 5
