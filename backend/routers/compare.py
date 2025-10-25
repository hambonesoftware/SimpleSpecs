"""Risk comparison endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.pdf_native import parse_pdf
from ..services.spec_compare import (
    ClauseMatch,
    ComplianceLLMClient,
    RiskReport,
    generate_risk_report,
)
from ..services.spec_extraction import SpecLLMClient, extract_specifications

router = APIRouter(prefix="/api", tags=["risk"])


class ClauseMatchPayload(BaseModel):
    """Schema describing the comparison result for a baseline clause."""

    clause_id: str
    discipline: str
    text: str
    mandatory: bool
    matched: bool
    score: float = Field(ge=0.0, le=1.0)
    missing_terms: list[str]
    best_line: dict | None = None

    @classmethod
    def from_match(cls, match: ClauseMatch) -> "ClauseMatchPayload":
        payload = match.to_dict()
        return cls(**payload)


class RiskReportPayload(BaseModel):
    """API response containing the generated risk report."""

    document_id: int
    overall_score: float = Field(ge=0.0, le=1.0)
    coverage_by_discipline: dict[str, float]
    missing_clause_ids: list[str]
    findings: list[ClauseMatchPayload]
    compliance_notes: list[dict] | None = None

    @classmethod
    def from_report(cls, report: RiskReport) -> "RiskReportPayload":
        data = report.to_dict()
        return cls(
            document_id=data["document_id"],
            overall_score=data["overall_score"],
            coverage_by_discipline=data["coverage_by_discipline"],
            missing_clause_ids=data["missing_clause_ids"],
            findings=[ClauseMatchPayload.from_match(match) for match in report.findings],
            compliance_notes=data.get("compliance_notes"),
        )


@router.post("/specs/compare/{document_id}", response_model=RiskReportPayload)
async def compare_specifications(
    document_id: int,
    *,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RiskReportPayload:
    """Return a risk assessment comparing extracted specs to the baseline."""

    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    document_path = settings.upload_dir / str(document.id) / document.filename
    if not document_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document contents missing")

    parse_result = parse_pdf(document_path, settings=settings)
    spec_llm = SpecLLMClient(settings)
    extraction = extract_specifications(parse_result, settings=settings, llm_client=spec_llm)
    compliance_client = ComplianceLLMClient(settings)
    report = generate_risk_report(
        document.id,
        extraction,
        settings=settings,
        compliance_client=compliance_client,
    )
    return RiskReportPayload.from_report(report)


__all__ = ["router"]
