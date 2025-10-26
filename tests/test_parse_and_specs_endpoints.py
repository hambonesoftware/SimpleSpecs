"""Integration tests covering parse and specification-related endpoints."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult
from backend.services.spec_compare import ClauseMatch, RiskClause, RiskReport
from backend.services.spec_extraction import SpecExtractionResult, SpecLine

PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def _upload_sample(client: TestClient) -> int:
    response = client.post(
        "/api/upload",
        files={"file": ("sample.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
    )
    assert response.status_code in {200, 201}
    return response.json()["id"]


def _sample_parse_result() -> ParseResult:
    block = ParsedBlock(
        text="Section 1\n- Requirement line",
        bbox=(0.0, 0.0, 100.0, 20.0),
        font="Helvetica",
        font_size=12.0,
    )
    page = ParsedPage(page_number=0, width=612.0, height=792.0, blocks=[block])
    return ParseResult(pages=[page], has_ocr=False, used_mineru=False)


def _sample_spec_result() -> SpecExtractionResult:
    line = SpecLine(
        text="Requirement line",
        page=0,
        header_path=("Section 1",),
        disciplines=("mechanical",),
        scores={"mechanical": 0.9},
        source="rule",
        block_index=0,
        line_index=0,
        bbox=None,
    )
    return SpecExtractionResult(lines=[line], disciplines=("mechanical", "electrical"))


def test_parse_endpoint_returns_stubbed_payload(
    client: TestClient, monkeypatch
) -> None:
    document_id = _upload_sample(client)
    sample_result = _sample_parse_result()

    def _mock_parse(document_path, *, settings):  # noqa: ANN001 - test helper
        return sample_result

    monkeypatch.setattr("backend.routers.parse.parse_pdf", _mock_parse)

    response = client.post(f"/api/parse/{document_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["has_ocr"] is False
    assert payload["used_mineru"] is False
    assert payload["pages"][0]["blocks"][0]["text"] == "Section 1\n- Requirement line"


def test_spec_extraction_endpoint_returns_buckets(
    client: TestClient, monkeypatch
) -> None:
    document_id = _upload_sample(client)
    sample_parse = _sample_parse_result()
    sample_spec = _sample_spec_result()

    monkeypatch.setattr(
        "backend.routers.specs.parse_pdf", lambda *args, **kwargs: sample_parse
    )
    monkeypatch.setattr(
        "backend.routers.specs.extract_specifications",
        lambda *args, **kwargs: sample_spec,
    )

    response = client.post(f"/api/specs/extract/{document_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert "mechanical" in payload["buckets"]
    assert payload["buckets"]["mechanical"][0]["text"] == "Requirement line"


def test_spec_compare_endpoint_returns_report(client: TestClient, monkeypatch) -> None:
    document_id = _upload_sample(client)
    sample_parse = _sample_parse_result()
    sample_spec = _sample_spec_result()

    clause = RiskClause(
        id="mech-1",
        discipline="mechanical",
        text="Requirement line",
        mandatory=True,
        keywords=("requirement", "line"),
    )
    match = ClauseMatch(
        clause=clause,
        score=1.0,
        matched=True,
        best_line=sample_spec.lines[0],
        missing_terms=tuple(),
    )
    report = RiskReport(
        document_id=document_id,
        findings=(match,),
        coverage_by_discipline={"mechanical": 1.0},
        overall_score=1.0,
        missing_clause_ids=tuple(),
        compliance_notes=({"clause_id": "mech-1", "action": "ok"},),
    )

    monkeypatch.setattr(
        "backend.routers.compare.parse_pdf", lambda *args, **kwargs: sample_parse
    )
    monkeypatch.setattr(
        "backend.routers.compare.extract_specifications",
        lambda *args, **kwargs: sample_spec,
    )
    monkeypatch.setattr(
        "backend.routers.compare.generate_risk_report", lambda *args, **kwargs: report
    )

    response = client.post(f"/api/specs/compare/{document_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["overall_score"] == 1.0
    assert payload["findings"][0]["clause_id"] == "mech-1"
    assert payload["coverage_by_discipline"]["mechanical"] == 1.0
