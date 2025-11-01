from pathlib import Path

import pytest

from backend.resources.golden_headers import MFC_5M_R2001_E1985
from backend.services.header_report import generate_header_alignment_report


def test_header_alignment_report_finds_all_golden_headers(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    pdf_path = repo_root / "MFC-5M_R2001_E1985.pdf"
    if not pdf_path.exists():
        pytest.skip("Sample document MFC-5M_R2001_E1985.pdf missing")

    monkeypatch.setenv("HEADERS_LLM_STRICT", "true")

    report = generate_header_alignment_report(pdf_path, MFC_5M_R2001_E1985)

    assert len(report) == len(MFC_5M_R2001_E1985)
    assert all(entry["found"] for entry in report)
    numbers = [entry["number"] for entry in report]
    assert numbers == [header["number"] for header in MFC_5M_R2001_E1985]
