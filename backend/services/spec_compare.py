"""Specification comparison and risk scoring utilities."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..config import Settings
from .llm import LLMCircuitOpenError, LLMProviderError, LLMService
from .spec_extraction import SpecExtractionResult, SpecLine

LOGGER = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w-]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "for",
    "in",
    "of",
    "per",
    "shall",
    "should",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class RiskClause:
    """Baseline clause that the extracted specification lines are compared against."""

    id: str
    discipline: str
    text: str
    mandatory: bool = True
    keywords: tuple[str, ...] = ()

    def token_set(self) -> set[str]:
        """Return the canonical token set representing the clause."""

        chunks = [tokenise(keyword) for keyword in self.keywords if keyword.strip()]
        flat_tokens: set[str] = set()
        for chunk in chunks:
            flat_tokens.update(chunk)
        if not flat_tokens:
            flat_tokens = tokenise(self.text)
        return flat_tokens


@dataclass
class ClauseMatch:
    """Match information for a baseline clause against extracted lines."""

    clause: RiskClause
    score: float
    matched: bool
    best_line: SpecLine | None
    missing_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialise the clause match for API responses."""

        payload: dict[str, object] = {
            "clause_id": self.clause.id,
            "discipline": self.clause.discipline,
            "text": self.clause.text,
            "mandatory": self.clause.mandatory,
            "matched": self.matched,
            "score": round(self.score, 3),
            "missing_terms": list(self.missing_terms),
        }
        if self.best_line is not None:
            payload["best_line"] = self.best_line.to_dict()
        else:
            payload["best_line"] = None
        return payload


@dataclass
class RiskReport:
    """Aggregate comparison result summarising clause matches and coverage."""

    document_id: int
    findings: tuple[ClauseMatch, ...]
    coverage_by_discipline: Mapping[str, float]
    overall_score: float
    missing_clause_ids: tuple[str, ...]
    compliance_notes: Sequence[Mapping[str, object]] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON serialisable representation of the report."""

        return {
            "document_id": self.document_id,
            "overall_score": round(self.overall_score, 3),
            "coverage_by_discipline": {
                discipline: round(score, 3)
                for discipline, score in self.coverage_by_discipline.items()
            },
            "missing_clause_ids": list(self.missing_clause_ids),
            "findings": [match.to_dict() for match in self.findings],
            "compliance_notes": list(self.compliance_notes)
            if self.compliance_notes is not None
            else None,
        }


class ComplianceLLMClient:
    """LLM client responsible for generating compliance guidance."""

    def __init__(
        self, settings: Settings, llm_service: LLMService | None = None
    ) -> None:
        self._settings = settings
        self._llm = llm_service or LLMService(settings)

    @property
    def is_enabled(self) -> bool:
        return self._llm.is_enabled

    def analyse(
        self, document_id: int, missing: Sequence[ClauseMatch]
    ) -> Sequence[Mapping[str, object]] | None:
        """Return structured compliance guidance when the provider is enabled."""

        if not self.is_enabled:
            return None

        missing_payload = [
            {"clause_id": match.clause.id, "description": match.clause.text}
            for match in missing
            if not match.matched and match.clause.mandatory
        ]
        if not missing_payload:
            return None

        prompt_lines = [
            "You are a compliance analyst generating remediation advice for missing specification clauses.",
            "Respond using JSON enclosed in #compliance# fences with a list of recommended actions.",
            f"Document ID: {document_id}",
            "Missing Clauses:",
            json.dumps(missing_payload, ensure_ascii=False),
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Provide concise remediation guidance. Respond ONLY with JSON inside #compliance# fences."
                ),
            },
            {"role": "user", "content": "\n".join(prompt_lines)},
        ]

        try:
            result = self._llm.generate(
                messages=messages,
                fence="#compliance#",
                metadata={"task": "risk-compliance"},
            )
        except (
            LLMCircuitOpenError,
            LLMProviderError,
        ) as exc:  # pragma: no cover - network path
            LOGGER.warning("Compliance LLM failed: %s", exc)
            return None

        fenced = result.fenced or result.content
        try:
            parsed = json.loads(fenced)
        except json.JSONDecodeError:
            LOGGER.warning("Compliance LLM returned invalid JSON")
            return None

        if isinstance(parsed, list):
            normalised: list[Mapping[str, object]] = []
            for entry in parsed:
                if isinstance(entry, Mapping):
                    normalised.append(dict(entry))
            return normalised or None
        if isinstance(parsed, Mapping):
            return [dict(parsed)]
        return None


def tokenise(text: str) -> set[str]:
    """Return a set of lowercase tokens for a line of text."""

    tokens = {match.group(0).lower() for match in _WORD_RE.finditer(text)}
    return {token for token in tokens if token not in _STOPWORDS and len(token) > 1}


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    return intersection / union


def _group_lines_by_discipline(lines: Sequence[SpecLine]) -> dict[str, list[SpecLine]]:
    grouped: dict[str, list[SpecLine]] = {}
    for line in lines:
        if line.disciplines:
            for discipline in line.disciplines:
                grouped.setdefault(discipline.lower(), []).append(line)
        else:
            grouped.setdefault("unknown", []).append(line)
    return grouped


def _evaluate_clause(
    clause: RiskClause,
    lines: Sequence[SpecLine],
    *,
    threshold: float,
) -> ClauseMatch:
    clause_tokens = clause.token_set()
    best_score = 0.0
    best_line: SpecLine | None = None
    best_tokens: set[str] = set()

    for line in lines:
        line_tokens = tokenise(line.text)
        coverage = (
            (len(clause_tokens & line_tokens) / len(clause_tokens))
            if clause_tokens
            else 0.0
        )
        similarity = _jaccard_similarity(clause_tokens, line_tokens)
        score = max(coverage, similarity)
        if score > best_score:
            best_score = score
            best_line = line
            best_tokens = line_tokens

    matched = best_score >= threshold
    missing_terms = (
        tuple(sorted(clause_tokens - best_tokens)) if clause_tokens else tuple()
    )
    return ClauseMatch(
        clause=clause,
        score=best_score,
        matched=matched,
        best_line=best_line,
        missing_terms=missing_terms,
    )


def load_baseline_clauses(path: Path) -> tuple[RiskClause, ...]:
    """Load baseline clauses from a JSON document."""

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_clauses = data.get("clauses", []) if isinstance(data, Mapping) else []
    clauses: list[RiskClause] = []
    for entry in raw_clauses:
        if not isinstance(entry, Mapping):
            continue
        clause_id = str(entry.get("id") or "").strip()
        discipline = str(entry.get("discipline") or "").strip().lower()
        text = str(entry.get("text") or "").strip()
        if not clause_id or not discipline or not text:
            continue
        mandatory = bool(entry.get("mandatory", True))
        keywords_raw = entry.get("keywords")
        keywords: tuple[str, ...]
        if isinstance(keywords_raw, Sequence) and not isinstance(
            keywords_raw, (str, bytes)
        ):
            keywords = tuple(
                str(item).strip() for item in keywords_raw if str(item).strip()
            )
        else:
            keywords = tuple()
        clauses.append(
            RiskClause(
                id=clause_id,
                discipline=discipline,
                text=text,
                mandatory=mandatory,
                keywords=keywords,
            )
        )
    return tuple(clauses)


def generate_risk_report(
    document_id: int,
    extraction: SpecExtractionResult,
    *,
    settings: Settings,
    threshold: float = 0.55,
    clauses: Sequence[RiskClause] | None = None,
    persist: bool = True,
    compliance_client: ComplianceLLMClient | None = None,
) -> RiskReport:
    """Compare extracted specifications against the baseline and build a risk report."""

    if clauses is None:
        clauses = load_baseline_clauses(settings.risk_baselines_path)
    if not clauses:
        raise ValueError("No baseline clauses are available for risk scoring")

    grouped_lines = _group_lines_by_discipline(extraction.lines)
    findings: list[ClauseMatch] = []
    for clause in clauses:
        discipline_lines = grouped_lines.get(clause.discipline.lower())
        candidate_lines: Sequence[SpecLine]
        if discipline_lines:
            candidate_lines = discipline_lines
        else:
            candidate_lines = extraction.lines
        findings.append(_evaluate_clause(clause, candidate_lines, threshold=threshold))

    mandatory_clauses = [clause for clause in clauses if clause.mandatory]
    mandatory_total = len(mandatory_clauses)
    matched_mandatory = sum(
        1 for match in findings if match.clause.mandatory and match.matched
    )
    overall_score = matched_mandatory / mandatory_total if mandatory_total else 1.0

    coverage_by_discipline: dict[str, float] = {}
    clauses_by_discipline: dict[str, list[RiskClause]] = {}
    for clause in clauses:
        clauses_by_discipline.setdefault(clause.discipline.lower(), []).append(clause)
    for discipline, discipline_clauses in clauses_by_discipline.items():
        discipline_mandatory = [
            clause for clause in discipline_clauses if clause.mandatory
        ]
        if not discipline_mandatory:
            continue
        discipline_matches = sum(
            1
            for match in findings
            if match.clause.mandatory
            and match.clause.discipline.lower() == discipline
            and match.matched
        )
        coverage_by_discipline[discipline] = discipline_matches / len(
            discipline_mandatory
        )

    missing_clause_ids = tuple(
        match.clause.id
        for match in findings
        if match.clause.mandatory and not match.matched
    )

    compliance_notes: Sequence[Mapping[str, object]] | None = None
    if compliance_client is not None:
        compliance_notes = compliance_client.analyse(document_id, findings)

    report = RiskReport(
        document_id=document_id,
        findings=tuple(findings),
        coverage_by_discipline=coverage_by_discipline,
        overall_score=overall_score,
        missing_clause_ids=missing_clause_ids,
        compliance_notes=compliance_notes,
    )

    if persist:
        report_path = settings.upload_dir / str(document_id) / "risk_report.json"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - filesystem failure
            LOGGER.warning("Unable to persist risk report: %s", exc)

    return report


__all__ = [
    "ClauseMatch",
    "ComplianceLLMClient",
    "RiskClause",
    "RiskReport",
    "generate_risk_report",
    "load_baseline_clauses",
    "tokenise",
]
