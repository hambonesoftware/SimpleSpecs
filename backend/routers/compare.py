"""Risk comparison endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.artifact_store import get_or_create_parse_result
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
        best_line = match.best_line.to_dict() if match.best_line else None
        return cls(
            clause_id=match.clause.id,
            discipline=match.clause.discipline,
            text=match.clause.text,
            mandatory=match.clause.mandatory,
            matched=match.matched,
            score=round(match.score, 3),
            missing_terms=list(match.missing_terms),
            best_line=best_line,
        )


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
        findings = [ClauseMatchPayload.from_match(match) for match in report.findings]
        compliance_notes = (
            [dict(note) for note in report.compliance_notes]
            if report.compliance_notes is not None
            else None
        )
        return cls(
            document_id=report.document_id,
            overall_score=round(report.overall_score, 3),
            coverage_by_discipline={
                key: round(value, 3)
                for key, value in report.coverage_by_discipline.items()
            },
            missing_clause_ids=list(report.missing_clause_ids),
            findings=findings,
            compliance_notes=compliance_notes,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    if document.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document is missing a primary key",
        )

    doc_id = document.id
    document_path = settings.upload_dir / str(doc_id) / document.filename
    if not document_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document contents missing"
        )

    parse_result, _ = get_or_create_parse_result(
        session=session,
        document=document,
        document_path=document_path,
        settings=settings,
        parse_func=parse_pdf,
    )
    spec_llm = SpecLLMClient(settings)
    extraction = extract_specifications(
        parse_result, settings=settings, llm_client=spec_llm
    )
    compliance_client = ComplianceLLMClient(settings)

    report = generate_risk_report(
        doc_id,
        extraction,
        settings=settings,
        compliance_client=compliance_client,
    )
    return RiskReportPayload.from_report(report)


__all__ = ["router"]
