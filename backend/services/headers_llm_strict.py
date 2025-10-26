"""Strict header extraction path using a single fenced LLM call."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Mapping, Protocol, Sequence, Tuple

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


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


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


def _find_header_line(
    header_text: str,
    lines: Sequence[BodyLine],
) -> Tuple[int, int, int] | None:
    """Return (list_index, global_idx, page) for the header text."""

    target = _normalise(header_text)
    candidates: List[Tuple[int, int, int]] = []

    for idx, line in enumerate(lines):
        if not _is_body_candidate(line):
            continue
        text = str(line.get("text", ""))
        if _normalise(text) == target:
            candidates.append(
                (
                    idx,
                    int(line.get("global_idx", idx)),
                    int(line.get("page", 0)),
                )
            )

    if not candidates:
        for idx, line in enumerate(lines):
            if not _is_body_candidate(line):
                continue
            text = str(line.get("text", ""))
            if _normalise(text).startswith(target):
                candidates.append(
                    (
                        idx,
                        int(line.get("global_idx", idx)),
                        int(line.get("page", 0)),
                    )
                )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[1])
    return candidates[-1]


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

    located: List[Dict[str, Any]] = []

    for header in _extract_headers(payload):
        position = _find_header_line(header["text"], lines)
        if not position:
            log.debug("Header not located in body: %s", header["text"])
            continue
        list_index, global_idx, page = position
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
