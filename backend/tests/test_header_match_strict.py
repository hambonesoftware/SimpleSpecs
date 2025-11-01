"""Tests for strict header alignment when HEADERS_LLM_STRICT is enabled."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from backend.config import reset_settings_cache
from backend.services.header_match import find_header_occurrences
from backend.services.pdf_native import parse_pdf_to_lines

GOLDEN_HEADERS = [
    {"title": "1 General", "number": "1", "level": 1, "page": 0},
    {
        "title": "1.1 Scope and Field of Application",
        "number": "1.1",
        "level": 2,
        "page": 0,
    },
    {"title": "1.2 References", "number": "1.2", "level": 2, "page": 0},
    {"title": "1.3 Definitions", "number": "1.3", "level": 2, "page": 0},
    {"title": "1.4 Symbols", "number": "1.4", "level": 2, "page": 0},
    {"title": "2 Principles", "number": "2", "level": 1, "page": 0},
    {
        "title": "2.1 Statement of the Principles",
        "number": "2.1",
        "level": 2,
        "page": 0,
    },
    {"title": "2.1.1 Static Weighing", "number": "2.1.1", "level": 3, "page": 0},
    {"title": "2.1.2 Dynamic Weighing", "number": "2.1.2", "level": 3, "page": 0},
    {
        "title": "2.1.3 Comparison of Instantaneous and Mean Flow Rate",
        "number": "2.1.3",
        "level": 3,
        "page": 0,
    },
    {
        "title": "2.2 Accuracy of the Method",
        "number": "2.2",
        "level": 2,
        "page": 0,
    },
    {
        "title": "2.2.1 Overall Uncertainty on the Weighing Measurement",
        "number": "2.2.1",
        "level": 3,
        "page": 0,
    },
    {
        "title": "2.2.2 Requirements for Accurate Measurements",
        "number": "2.2.2",
        "level": 3,
        "page": 0,
    },
    {"title": "3 Apparatus", "number": "3", "level": 1, "page": 0},
    {"title": "3.1 Diverter", "number": "3.1", "level": 2, "page": 0},
    {
        "title": "3.2 Time-Measuring Apparatus",
        "number": "3.2",
        "level": 2,
        "page": 0,
    },
    {"title": "3.3 Weighing Tank", "number": "3.3", "level": 2, "page": 0},
    {"title": "3.4 Weighing Device", "number": "3.4", "level": 2, "page": 0},
    {
        "title": "3.5 Auxiliary Measurements",
        "number": "3.5",
        "level": 2,
        "page": 0,
    },
    {"title": "4 Procedure", "number": "4", "level": 1, "page": 0},
    {
        "title": "4.1 Static Weighing Method",
        "number": "4.1",
        "level": 2,
        "page": 0,
    },
    {
        "title": "4.2 Dynamic Weighing Method",
        "number": "4.2",
        "level": 2,
        "page": 0,
    },
    {
        "title": "4.3 Common Provisions",
        "number": "4.3",
        "level": 2,
        "page": 0,
    },
    {"title": "5 Calculation of Flow Rate", "number": "5", "level": 1, "page": 0},
    {
        "title": "5.1 Calculation of Mass Flow Rate",
        "number": "5.1",
        "level": 2,
        "page": 0,
    },
    {
        "title": "5.2 Calculation of Volume Flow Rate",
        "number": "5.2",
        "level": 2,
        "page": 0,
    },
    {
        "title": "6 Uncertainties in the Measurement of Flow Rate",
        "number": "6",
        "level": 1,
        "page": 0,
    },
]


def test_strict_header_search_matches_golden_outline(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pdf_path = repo_root / "MFC-5M_R2001_E1985.pdf"
    if not pdf_path.exists():
        pytest.skip("Sample document MFC-5M_R2001_E1985.pdf missing")

    export_dir = tmp_path / "exports"
    upload_dir = tmp_path / "uploads"
    log_dir = tmp_path / "logs"
    export_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("HEADERS_LOG_DIR", str(log_dir))
    monkeypatch.setenv("HEADERS_LLM_STRICT", "1")
    reset_settings_cache()

    lines = parse_pdf_to_lines(pdf_path)
    doc_id = 101
    doc_dir = export_dir / str(doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    per_page_counts: dict[int, int] = defaultdict(int)
    with (doc_dir / "lines.jsonl").open("w", encoding="utf-8") as handle:
        for entry in lines:
            page = int(entry.get("page", 0))
            per_page_counts[page] += 1
            payload = {
                "page": page,
                "line_in_page": per_page_counts[page],
                "text": str(entry.get("text", "")),
            }
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")

    matches = find_header_occurrences(None, doc_id, GOLDEN_HEADERS)

    assert matches
    assert len(matches) == len(GOLDEN_HEADERS)
    assert all(match["found"] for match in matches)
