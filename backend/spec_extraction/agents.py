"""Prompt construction and response normalisation for spec extraction agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

NORMATIVE_RE = re.compile(r"\b(shall|must|should|required)\b", re.IGNORECASE)
LEVEL_RE = re.compile(r"\b(shall|must|should|recommend(?:ed)?|may|can|optional)\b", re.IGNORECASE)
FENCE_RE = re.compile(r"```SIMPLEBUCKETS\s*(?P<payload>.*)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class AgentDefinition:
    code: str
    description: str
    domain_focus: str


_AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    "Mechanical": AgentDefinition(
        code="Mechanical",
        description="Mechanical discipline specialist",
        domain_focus="mechanical assemblies, structural components, thermal constraints",
    ),
    "Electrical": AgentDefinition(
        code="Electrical",
        description="Electrical discipline specialist",
        domain_focus="power distribution, wiring, electrical safety, grounding",
    ),
    "Controls": AgentDefinition(
        code="Controls",
        description="Controls and automation specialist",
        domain_focus="instrumentation, PLC/SCADA logic, interlocks, set-points",
    ),
    "Software": AgentDefinition(
        code="Software",
        description="Software and firmware specialist",
        domain_focus="embedded code, software interfaces, cybersecurity, testing",
    ),
    "ProjectManagement": AgentDefinition(
        code="ProjectManagement",
        description="Project management specialist",
        domain_focus="project controls, deliverables, reviews, stakeholder approvals",
    ),
}


def get_agent_definition(agent_code: str) -> AgentDefinition:
    """Return the agent definition for ``agent_code`` or raise ``KeyError``."""

    key = agent_code.strip()
    if key not in _AGENT_DEFINITIONS:
        raise KeyError(f"Unknown agent code: {agent_code}")
    return _AGENT_DEFINITIONS[key]


def build_messages(
    *,
    agent_code: str,
    section_title: str,
    section_text: str,
    page_start: int | None,
    page_end: int | None,
    retry_hint: str | None = None,
) -> list[dict[str, str]]:
    """Return system/user messages tailored to ``agent_code`` for the section."""

    definition = get_agent_definition(agent_code)
    page_str = _format_page_range(page_start, page_end)
    system_lines = [
        "You are an expert requirements analyst.",
        "Focus on the domain: " + definition.domain_focus + ".",
        "Extract clear, testable requirements.",
        (
            "Always respond with either ABORT or a single ```SIMPLEBUCKETS json``` fenced "
            "code block containing valid JSON that matches the required schema."
        ),
        "If you cannot comply exactly, respond with ABORT.",
        (
            "Map modal verbs: shall/must/required -> MUST; should/recommended -> SHOULD; "
            "may/can/optional -> MAY."
        ),
        "Ignore running headers, footers, and table-of-contents artefacts.",
    ]
    if retry_hint:
        system_lines.append(retry_hint)

    user_lines = [
        f"Section title: {section_title.strip() or 'Untitled Section'}",
    ]
    if page_str:
        user_lines.append(f"Pages: {page_str}")
    user_lines.append(
        "Return a JSON object with keys requirements (list) and notes (list). "
        "Each requirement entry must contain text (non-empty string), level (MUST/SHOULD/MAY), "
        "and page_hint (integer or null)."
    )
    user_lines.append("Source text:" )
    user_lines.append(section_text.strip())

    return [
        {"role": "system", "content": "\n".join(system_lines)},
        {"role": "user", "content": "\n\n".join(user_lines)},
    ]


def _format_page_range(page_start: int | None, page_end: int | None) -> str:
    if page_start is None and page_end is None:
        return ""
    if page_start is None:
        return f"up to page {page_end}"
    if page_end is None or page_end == page_start:
        return f"page {page_start}"
    return f"pages {page_start}-{page_end}"


def extract_payload(raw: str) -> str | None:
    """Return the JSON payload contained within the SIMPLEBUCKETS fence."""

    match = FENCE_RE.search(raw.strip())
    if not match:
        return None
    return match.group("payload").strip()


def parse_payload(raw: str) -> dict[str, Any]:
    """Parse and validate the JSON payload emitted by an agent."""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("Payload must be a JSON object")
    requirements = parsed.get("requirements", [])
    if not isinstance(requirements, list):
        raise ValueError("requirements must be a list")
    normalised_requirements = []
    for item in requirements:
        if not isinstance(item, Mapping):
            raise ValueError("Each requirement must be an object")
        text = str(item.get("text", "")).strip()
        if not text:
            raise ValueError("Requirement text cannot be empty")
        level = normalise_level(str(item.get("level", "")))
        page_hint = item.get("page_hint")
        if page_hint is not None:
            try:
                page_hint = int(page_hint)
            except (TypeError, ValueError) as exc:
                raise ValueError("page_hint must be an integer or null") from exc
        normalised_requirements.append(
            {
                "text": text,
                "level": level,
                "page_hint": page_hint,
            }
        )
    notes = parsed.get("notes", [])
    if isinstance(notes, list):
        notes = [str(note).strip() for note in notes if str(note).strip()]
    else:
        notes = []
    return {
        "requirements": normalised_requirements,
        "notes": notes,
    }


def normalise_level(raw: str) -> str:
    """Return a normalised modal level token."""

    token = raw.strip().lower()
    if token in {"must", "shall", "required", "requires"}:
        return "MUST"
    if token in {"should", "recommended", "recommend", "ought"}:
        return "SHOULD"
    if token in {"may", "can", "optional", "might"}:
        return "MAY"
    match = LEVEL_RE.search(raw)
    if match:
        return normalise_level(match.group(0))
    return "MUST"


def contains_normative_language(text: str) -> bool:
    """Return ``True`` when the text contains normative trigger words."""

    return bool(NORMATIVE_RE.search(text))


def build_format_retry_hint(errors: Iterable[str]) -> str:
    """Construct a retry instruction focusing on formatting issues."""

    reasons = "; ".join(errors)
    return (
        "Formatting correction: output must be a ```SIMPLEBUCKETS json``` fenced block "
        f"with valid JSON. Issues detected: {reasons}."
    )


def to_confidence_string(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.3f}"
