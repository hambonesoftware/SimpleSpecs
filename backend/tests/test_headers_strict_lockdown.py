from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.headers_llm_strict import (
    align_headers_llm_strict,
    normalize_strict_text,
)
from backend.services.pdf_native import parse_pdf_to_lines


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


def test_mfc_headers_align_with_golden_outline() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pdf_path = repo_root / "MFC-5M_R2001_E1985.pdf"
    if not pdf_path.exists():
        pytest.skip("Sample document MFC-5M_R2001_E1985.pdf missing")

    lines = parse_pdf_to_lines(pdf_path)
    for idx, line in enumerate(lines):
        line.setdefault("line_idx", idx)

    llm_headers = [
        {"text": "1 General", "number": "1", "level": 1},
        {"text": "1.1 Scope and Field of Application", "number": "1.1", "level": 2},
        {"text": "1.2 References", "number": "1.2", "level": 2},
        {"text": "1.3 Definitions", "number": "1.3", "level": 2},
        {"text": "1.4 Symbols", "number": "1.4", "level": 2},
        {"text": "2 Principles", "number": "2", "level": 1},
        {"text": "2.1 Statement of the Principles", "number": "2.1", "level": 2},
        {"text": "2.1.1 Static Weighing", "number": "2.1.1", "level": 3},
        {"text": "2.1.2 Dynamic Weighing", "number": "2.1.2", "level": 3},
        {
            "text": "2.1.3 Comparison of Instantaneous and Mean Flow Rate",
            "number": "2.1.3",
            "level": 3,
        },
        {"text": "2.2 Accuracy of the Method", "number": "2.2", "level": 2},
        {
            "text": "2.2.1 Overall Uncertainty on the Weighing Measurement",
            "number": "2.2.1",
            "level": 3,
        },
        {
            "text": "2.2.2 Requirements for Accurate Measurements",
            "number": "2.2.2",
            "level": 3,
        },
        {"text": "3 Apparatus", "number": "3", "level": 1},
        {"text": "3.1 Diverter", "number": "3.1", "level": 2},
        {"text": "3.2 Time-Measuring Apparatus", "number": "3.2", "level": 2},
        {"text": "3.3 Weighing Tank", "number": "3.3", "level": 2},
        {"text": "3.4 Weighing Device", "number": "3.4", "level": 2},
        {"text": "3.5 Auxiliary Measurements", "number": "3.5", "level": 2},
        {"text": "4 Procedure", "number": "4", "level": 1},
        {"text": "4.1 Static Weighing Method", "number": "4.1", "level": 2},
        {"text": "4.2 Dynamic Weighing Method", "number": "4.2", "level": 2},
        {"text": "4.3 Common Provisions", "number": "4.3", "level": 2},
        {"text": "5 Calculation of Flow Rate", "number": "5", "level": 1},
        {"text": "5.1 Calculation of Mass Flow Rate", "number": "5.1", "level": 2},
        {"text": "5.2 Calculation of Volume Flow Rate", "number": "5.2", "level": 2},
        {
            "text": "6 Uncertainties in the Measurement of Flow Rate",
            "number": "6",
            "level": 1,
        },
    ]

    resolved = align_headers_llm_strict(llm_headers, lines, tracer=None)
    assert len(resolved) == len(llm_headers)

    resolved_numbers = [item["header"]["number"] for item in resolved]
    assert set(resolved_numbers) == {header["number"] for header in llm_headers}

    resolved_positions = [item["line"]["global_idx"] for item in resolved]
    assert resolved_positions == sorted(resolved_positions)
    assert len(resolved_positions) == len(set(resolved_positions))
