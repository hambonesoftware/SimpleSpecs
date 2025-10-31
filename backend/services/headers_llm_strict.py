"""Strict header extraction path using a single fenced LLM call."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Protocol, Sequence, Tuple

try:  # pragma: no cover - optional dependency in some environments
    from rapidfuzz.fuzz import token_set_ratio as _rf_token_set_ratio
except Exception:  # pragma: no cover - fallback for minimal installs
    from difflib import SequenceMatcher

    def token_set_ratio(a: str, b: str) -> int:
        return int(SequenceMatcher(None, a, b).ratio() * 100)

else:  # pragma: no cover - passthrough when rapidfuzz is available
    token_set_ratio = _rf_token_set_ratio

from ..utils.trace import HeaderTracer

log = logging.getLogger(__name__)

FENCE = "#headers#"

PROMPT_TEMPLATE = """Return ONLY the fenced JSON below.

{fence}
{{
  "headers": [
    {{"text":"<exact printed heading text>","number": "<printed number like 1, 1.2.3, A, A.1 or null>", "level": <positive integer>}}
  ]
}}
{fence}

Rules (non-negotiable):
- Include ONLY headings/subheadings that appear in the MAIN BODY.
- EXCLUDE anything from a Contents/Table of Contents, any Index, any Glossary, and any running headers/footers.
- Copy numbering EXACTLY as printed when present; if none, set "number": null. Do not infer or normalize.
- Preserve the original document order.
- No prose outside the fenced JSON.
- If unsure, omit the item.

Document:
<BEGIN>
{doc_text}
<END>
"""


BodyLine = Dict[str, Any]


def _is_toc_or_index_line(text: str) -> bool:
    trimmed = text.strip()
    if not trimmed:
        return False
    upper = trimmed.upper()
    if upper in {"CONTENTS", "TABLE OF CONTENTS", "INDEX"}:
        return True
    if re.search(r"\.{2,}\s*\d+\s*$", trimmed):
        return True
    return False


DOT_VARIANTS = ".\u2024\u2027"
DOT_CASCADE_RE = re.compile(rf"(\d)\s*[{DOT_VARIANTS}]\s*(\d)")
IL_MIDDLE_RE = re.compile(r"(?<=\d)\s*[Il]\s*(?=(?:\d|\b))")
IL_AFTER_DOT_RE = re.compile(rf"(?<=[{DOT_VARIANTS}])\s*[Il]\b")
WHITESPACE_RE = re.compile(r"\s+")
APPENDIX_LINE_RE = re.compile(r"^APPENDIX\s+[A-Z0-9]+$", re.IGNORECASE)
NBSP_TRANSLATION = str.maketrans({"\u00A0": " ", "\u2007": " ", "\u2009": " "})
BAND_LIMIT = 3
NUMERIC_THRESHOLD = 74
TITLE_THRESHOLD = 80


def _pre_normalise(value: str) -> str:
    cleaned = value.translate(NBSP_TRANSLATION)
    cleaned = DOT_CASCADE_RE.sub(r"\1.\2", cleaned)
    cleaned = cleaned.replace("\u2024", ".").replace("\u2027", ".")
    cleaned = IL_MIDDLE_RE.sub("1", cleaned)
    cleaned = IL_AFTER_DOT_RE.sub("1", cleaned)
    return cleaned


def _normalise(text: str) -> str:
    cleaned = _pre_normalise(text)
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip().casefold()


def _is_body_candidate(line: BodyLine) -> bool:
    text = str(line.get("text", ""))
    if not text.strip():
        return False
    if line.get("is_toc") or line.get("is_index"):
        return False
    if line.get("is_running"):
        return False
    if _is_toc_or_index_line(text):
        return False
    return True


def _compile_number_regex(number: str) -> re.Pattern[str]:
    cleaned = WHITESPACE_RE.sub(" ", _pre_normalise(number)).strip()
    if not cleaned:
        raise ValueError("empty number pattern")
    escaped = re.escape(cleaned)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\.", rf"\s*[{DOT_VARIANTS}]\s*")
    return re.compile(rf"^\s*{escaped}\b(?![{DOT_VARIANTS}])", re.IGNORECASE)


def _is_all_caps(value: str) -> bool:
    letters = re.sub(r"[^A-Za-z0-9]", "", value)
    return bool(letters) and letters.upper() == letters


def _appendix_merge_text(index: int, lines: Sequence[BodyLine]) -> str:
    current = str(lines[index].get("text", ""))
    stripped = current.strip()
    if not APPENDIX_LINE_RE.match(stripped):
        return current
    if index + 1 >= len(lines):
        return current
    next_text = str(lines[index + 1].get("text", "")).strip()
    if not next_text:
        return current
    if _is_all_caps(next_text):
        return f"{current} {next_text}"
    return current


def _band_indices(lines: Sequence[BodyLine]) -> set[int]:
    per_page: Dict[int, List[Tuple[int, int]]] = {}
    for idx, line in enumerate(lines):
        if not _is_body_candidate(line):
            continue
        page = int(line.get("page", 0) or 0)
        global_idx = int(line.get("global_idx", idx) or idx)
        per_page.setdefault(page, []).append((global_idx, idx))

    banded: set[int] = set()
    for entries in per_page.values():
        entries.sort(key=lambda item: item[0])
        if not entries:
            continue
        tops = entries[:BAND_LIMIT]
        bots = entries[-BAND_LIMIT:] if len(entries) > BAND_LIMIT else entries
        for _, idx in tops + bots:
            banded.add(idx)
    return banded


@dataclass(slots=True)
class PreparedLine:
    index: int
    text: str
    page: int
    global_idx: int
    line_idx: int
    combined_normalised: str
    prenormalised: str
    is_candidate: bool
    in_band: bool


def _prepare_lines(lines: Sequence[BodyLine]) -> List[PreparedLine]:
    banded = _band_indices(lines)
    prepared: List[PreparedLine] = []
    for idx, line in enumerate(lines):
        text = str(line.get("text", ""))
        merged = _appendix_merge_text(idx, lines)
        prepared.append(
            PreparedLine(
                index=idx,
                text=text,
                page=int(line.get("page", 0) or 0),
                global_idx=int(line.get("global_idx", idx) or idx),
                line_idx=int(line.get("line_idx", idx) or idx),
                combined_normalised=_normalise(merged),
                prenormalised=WHITESPACE_RE.sub(" ", _pre_normalise(text)).casefold(),
                is_candidate=_is_body_candidate(line),
                in_band=idx in banded,
            )
        )
    return prepared


def _select_best(current: Tuple[int, int, PreparedLine] | None, score: int, line: PreparedLine) -> Tuple[int, int, PreparedLine]:
    if current is None:
        return (score, line.global_idx, line)
    best_score, best_idx, _ = current
    if score > best_score:
        return (score, line.global_idx, line)
    if score == best_score and line.global_idx < best_idx:
        return (score, line.global_idx, line)
    return current


def _find_header_line(
    header: Mapping[str, Any],
    prepared_lines: Sequence[PreparedLine],
) -> PreparedLine | None:
    title = str(header.get("text", ""))
    title_norm = _normalise(title)
    if not title_norm:
        return None

    number_value = header.get("number")
    number_regex: re.Pattern[str] | None = None
    combined_target = title_norm
    if isinstance(number_value, str) and number_value.strip():
        try:
            number_regex = _compile_number_regex(number_value)
            combined_target = _normalise(f"{number_value} {title}")
        except ValueError:
            number_regex = None

    best_numeric: Tuple[int, int, PreparedLine] | None = None
    best_title: Tuple[int, int, PreparedLine] | None = None

    for prepared in prepared_lines:
        if not prepared.is_candidate:
            continue

        has_number = False
        numeric_score = -1
        if number_regex is not None:
            if number_regex.search(prepared.prenormalised):
                has_number = True
                numeric_score = token_set_ratio(
                    prepared.combined_normalised, combined_target
                )

        if prepared.in_band and not has_number:
            continue

        if has_number and numeric_score >= NUMERIC_THRESHOLD:
            best_numeric = _select_best(best_numeric, numeric_score, prepared)
            continue

        title_score = token_set_ratio(prepared.combined_normalised, title_norm)
        if number_regex is not None and has_number and numeric_score >= 0:
            # numeric evidence but below threshold – allow fallback with slight boost
            title_score += 2

        if title_score >= TITLE_THRESHOLD:
            best_title = _select_best(best_title, title_score, prepared)

    if best_numeric is not None:
        return best_numeric[2]
    if best_title is not None:
        return best_title[2]
    return None


def _coerce_level(value: Any) -> int:
    try:
        level = int(value)
    except Exception:
        level = 1
    return max(1, level)


def _extract_headers(payload: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    headers = payload.get("headers")
    if not isinstance(headers, list):
        return []
    for entry in headers:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        number = entry.get("number")
        if isinstance(number, str):
            number = number.strip() or None
        elif number is None:
            number = None
        else:
            number = str(number).strip() or None
        yield {
            "text": text,
            "number": number,
            "level": _coerce_level(entry.get("level")),
        }


class _SupportsGenerate(Protocol):
    def generate(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        fence: str | None = None,
        params: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        ...


def extract_headers_and_sections_strict(
    *,
    llm: _SupportsGenerate,
    lines: Sequence[BodyLine],
    tracer: HeaderTracer | None = None,
) -> Dict[str, Any]:
    """Locate headers and construct contiguous section ranges."""

    full_text = "\n".join(str(line.get("text", "")) for line in lines)

    prompt = PROMPT_TEMPLATE.format(fence=FENCE, doc_text=full_text)
    result = llm.generate(messages=[{"role": "user", "content": prompt}], fence=FENCE)

    if not result.fenced:
        raise RuntimeError("LLM response missing fenced JSON")

    try:
        payload = json.loads(result.fenced)
    except json.JSONDecodeError as exc:
        log.error("Failed to decode headers JSON: %s", exc)
        payload = {}

    llm_headers = list(_extract_headers(payload))
    prepared_lines = _prepare_lines(lines)
    if tracer is not None:
        tracer.ev(
            "llm_outline_received",
            count=len(llm_headers),
            headers=[{**header} for header in llm_headers],
        )

    located: List[Dict[str, Any]] = []

    for header in llm_headers:
        prepared = _find_header_line(header, prepared_lines)
        if not prepared:
            log.debug("Header not located in body: %s", header["text"])
            if tracer is not None:
                tracer.ev("candidate_missing", header={**header})
            continue
        list_index = prepared.index
        global_idx = prepared.global_idx
        page = prepared.page
        if tracer is not None:
            tracer.ev(
                "candidate_found",
                header_text=header["text"],
                header_number=header["number"],
                level=header["level"],
                page=page,
                line_index=list_index,
                global_idx=global_idx,
            )
        located.append(
            {
                "text": header["text"],
                "number": header["number"],
                "level": header["level"],
                "line_index": list_index,
                "start_global_index": global_idx,
                "start_page": page,
            }
        )

    located.sort(key=lambda item: item["start_global_index"])

    sections: List[Dict[str, Any]] = []
    if lines:
        for idx, header in enumerate(located):
            start_line_index = header["line_index"]
            if idx + 1 < len(located):
                next_line_index = located[idx + 1]["line_index"] - 1
            else:
                next_line_index = len(lines) - 1
            if next_line_index < start_line_index:
                next_line_index = start_line_index
            end_line = lines[next_line_index]
            sections.append(
                {
                    "text": header["text"],
                    "number": header.get("number"),
                    "level": header["level"],
                    "start_line_index": start_line_index,
                    "end_line_index": next_line_index,
                    "start_global_index": header["start_global_index"],
                    "end_global_index": int(
                        end_line.get("global_idx", header["start_global_index"])
                    ),
                    "start_page": header["start_page"],
                    "end_page": int(end_line.get("page", header["start_page"])),
                }
            )

    return {
        "headers": located,
        "sections": sections,
        "fenced_text": result.fenced,
    }


__all__ = ["extract_headers_and_sections_strict", "FENCE"]
