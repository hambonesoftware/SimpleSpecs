"""Tests for the risk comparison service."""

from __future__ import annotations

import json

import pytest

from backend.config import Settings
from backend.services.spec_compare import RiskClause, generate_risk_report
from backend.services.spec_extraction import SpecExtractionResult, SpecLine


def _make_line(text: str, *, disciplines: tuple[str, ...]) -> SpecLine:
    return SpecLine(
        text=text,
        page=0,
        header_path=tuple(),
        disciplines=disciplines,
        scores={},
        source="rule",
        block_index=0,
        line_index=0,
        bbox=None,
    )


def test_risk_report_detects_missing_clause(tmp_path) -> None:
    """The report should flag mandatory clauses that are absent."""

    settings = Settings(upload_dir=tmp_path)
    clauses = (
        RiskClause(
            id="mech-pressure",
            discipline="mechanical",
            text="Pressure relief valves installed",
            keywords=("pressure", "relief", "valve"),
        ),
        RiskClause(
            id="mech-traceability",
            discipline="mechanical",
            text="Material traceability records available",
            keywords=("material", "traceability", "records"),
        ),
        RiskClause(
            id="elec-ground",
            discipline="electrical",
            text="Protective earth bonding",
            keywords=("earth", "bonding"),
        ),
    )
    extraction = SpecExtractionResult(
        lines=[
            _make_line(
                "The design includes a pressure relief valve sized per the latest code.",
                disciplines=("mechanical",),
            ),
            _make_line(
                "Each cabinet provides protective earth bonding in accordance with IEC 60204-1.",
                disciplines=("electrical",),
            ),
        ],
        disciplines=("mechanical", "electrical"),
    )

    report = generate_risk_report(
        41, extraction, settings=settings, clauses=clauses, persist=False
    )

    assert "mech-traceability" in report.missing_clause_ids
    assert report.coverage_by_discipline["mechanical"] == pytest.approx(0.5)
    assert report.coverage_by_discipline["electrical"] == pytest.approx(1.0)
    assert report.overall_score == pytest.approx(2 / 3)


def test_risk_report_detects_removed_clauses(tmp_path) -> None:
    """Simulated removals should be detected at or above the required threshold."""

    settings = Settings(upload_dir=tmp_path)
    clauses = tuple(
        RiskClause(
            id=f"ctrl-{index}",
            discipline="controls",
            text=f"Safety integrity requirement {index}",
            keywords=("safety", f"integrity{index}"),
        )
        for index in range(20)
    )
    # Provide only one matching line so that 19 clauses are flagged missing (95%+ detection).
    extraction = SpecExtractionResult(
        lines=[
            _make_line(
                "Safety integrity requirement 0 is implemented with redundancy.",
                disciplines=("controls",),
            )
        ],
        disciplines=("controls",),
    )

    report = generate_risk_report(
        55, extraction, settings=settings, clauses=clauses, persist=False
    )
    missing = [
        clause_id
        for clause_id in report.missing_clause_ids
        if clause_id.startswith("ctrl-")
    ]
    denominator = max(len(clauses) - 1, 1)
    detection_rate = len(missing) / denominator
    assert detection_rate >= 0.95


def test_risk_report_persists_to_disk(tmp_path) -> None:
    """A JSON payload should be written when persistence is enabled."""

    settings = Settings(upload_dir=tmp_path)
    clauses = (
        RiskClause(
            id="pm-approval",
            discipline="project_management",
            text="Change control board approval is required",
            keywords=("change", "control", "approval"),
        ),
    )
    extraction = SpecExtractionResult(
        lines=[
            _make_line(
                "A change control board approval is required for all customer releases.",
                disciplines=("project_management",),
            )
        ],
        disciplines=("project_management",),
    )

    report = generate_risk_report(
        72, extraction, settings=settings, clauses=clauses, persist=True
    )
    report_path = tmp_path / "72" / "risk_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["document_id"] == 72
    assert payload["missing_clause_ids"] == []
    assert report.overall_score == 1.0
