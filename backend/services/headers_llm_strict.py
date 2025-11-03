"""Strict header extraction path using a single fenced LLM call."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency in some environments
    from rapidfuzz.fuzz import token_set_ratio as _rf_token_set_ratio
except Exception:  # pragma: no cover - fallback for minimal installs
    from difflib import SequenceMatcher

    def token_set_ratio(a: str, b: str) -> int:
        return int(SequenceMatcher(None, a, b).ratio() * 100)

else:  # pragma: no cover - passthrough when rapidfuzz is available
    token_set_ratio = _rf_token_set_ratio

from ..config import (
    HEADERS_FINAL_MONOTONIC_GUARD,
    HEADERS_STRICT_AFTER_ANCHOR_ONLY,
    HEADERS_STRICT_BAND_LINES,
    HEADERS_STRICT_FUZZY_THRESH,
    HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK,
    HEADERS_STRICT_TITLE_ONLY_THRESH,
    HEADERS_STRICT_TOC_MIN_DOT_LEADERS,
    HEADERS_STRICT_TOC_MIN_SECTION_TOKENS,
)
from ..utils.errors import AlignmentPreconditionError, OutlineParseError

try:  # pragma: no cover - tracing is optional in some deployments
    from ..utils.trace import HeaderTracer
except Exception:  # pragma: no cover - tracing disabled
    HeaderTracer = None  # type: ignore[assignment]

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

DOTS = r"[.\u2024\u2027·]"
NBSPS = "\u00A0\u2007\u2009"
SOFT_HYPH = "\u00AD"

SPACED_DOTS_RE = re.compile(r"(?<=\d)\s*" + DOTS + r"\s*(?=\d)")
CONFUSABLE_ONE_RES = [
    re.compile(r"(?<=\d)\s*[Il]\s*(?=(?:\d|\b))"),
    re.compile(r"(?<=" + DOTS + r")\s*[Il]\b"),
]

DOTTED_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
SECTION_LIKE_RE = re.compile(r"^\s*\d+(?:\s*" + DOTS + r"\s*\d+)*\b")
APPENDIX_LINE_RE = re.compile(r"^\s*APPENDIX\s+[A-Z]\b", re.IGNORECASE)


def _collapse_spaced_dots(value: str) -> str:
    """Collapse spaced dot sequences like ``1 . 2`` → ``1.2`` until stable."""

    return SPACED_DOTS_RE.sub(".", value)


def normalize_strict_text(value: str) -> str:
    """Normalise text for strict matching while preserving printed intent."""

    cleaned = value.replace(SOFT_HYPH, "")
    for ch in NBSPS:
        cleaned = cleaned.replace(ch, " ")
    cleaned = _collapse_spaced_dots(cleaned)
    for rx in CONFUSABLE_ONE_RES:
        cleaned = rx.sub("1", cleaned)
    cleaned = _collapse_spaced_dots(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().casefold()


def compile_number_regex_fuzzy(number: str) -> re.Pattern[str]:
    """Compile a regex that tolerates spacing around dot separators."""

    number_pat = re.escape(number).replace(r"\.", r"\s*" + DOTS + r"\s*")
    return re.compile(r"(?<![0-9A-Za-z.])" + number_pat + r"\b(?!\.)", re.IGNORECASE)


def detect_toc_pages_strict(lines: Sequence[BodyLine]) -> set[int]:
    """Identify pages that resemble a Table of Contents."""

    from collections import defaultdict

    by_page = defaultdict(list)
    for entry in lines:
        try:
            page = int(entry.get("page", 0) or 0)
        except Exception:
            page = 0
        by_page[page].append(str(entry.get("text", "")))

    toc_pages: set[int] = set()
    for page, texts in by_page.items():
        dotted = sum(1 for text in texts if DOTTED_LEADER_RE.search(text))
        section_like = 0
        body_like = 0
        for text in texts:
            normalised = normalize_strict_text(text)
            if SECTION_LIKE_RE.search(normalised):
                section_like += 1
            if "." in text and len(normalised) >= 40:
                body_like += 1
        if dotted >= HEADERS_STRICT_TOC_MIN_DOT_LEADERS:
            toc_pages.add(page)
            continue
        if (
            section_like >= HEADERS_STRICT_TOC_MIN_SECTION_TOKENS
            and body_like <= max(1, section_like // 2)
        ):
            toc_pages.add(page)
    return toc_pages


def fuse_two_line_appendix_candidates(lines: Sequence[BodyLine]) -> List[BodyLine]:
    """Merge two-line appendix headings into a synthetic candidate."""

    fused: List[BodyLine] = []
    as_list = list(lines)
    total = len(as_list)
    index = 0
    while index < total:
        current = dict(as_list[index])
        text = str(current.get("text", ""))
        if APPENDIX_LINE_RE.match(text):
            lookahead = index + 1
            if lookahead < total:
                next_line = as_list[lookahead]
                next_text = str(next_line.get("text", "")).strip()
                if next_text:
                    combined = text.rstrip() + " " + next_text.lstrip()
                    current["_synthetic_text"] = combined
        fused.append(current)
        index += 1
    return fused


def align_headers_llm_strict(
    llm_headers: List[Dict[str, Any]],
    lines_input: Sequence[BodyLine],
    tracer: Optional[HeaderTracer] = None,
) -> List[Dict[str, Any]]:
    """Align LLM-provided headers to body lines using strict heuristics."""

    if tracer is not None:
        tracer.log_call(f"{__name__}.align_headers_llm_strict")

    lines_list = list(lines_input)
    raw_lines = fuse_two_line_appendix_candidates(lines_list)

    lines: List[Dict[str, Any]] = []
    for idx, entry in enumerate(raw_lines):
        text = str(entry.get("text", ""))
        if not text.strip():
            continue
        try:
            page = int(entry.get("page", 0) or 0)
        except Exception:
            page = 0
        try:
            global_idx = int(entry.get("global_idx", idx) or idx)
        except Exception:
            global_idx = idx
        line_idx_raw = entry.get("line_idx", entry.get("line_index"))
        if line_idx_raw is None:
            line_idx = idx
        else:
            try:
                line_idx = int(line_idx_raw)
            except Exception:
                line_idx = idx
        blocked = bool(
            entry.get("is_toc") or entry.get("is_index") or entry.get("is_running")
        )
        syn_text = entry.get("_synthetic_text")
        norm_syn = normalize_strict_text(syn_text) if syn_text else None
        lines.append(
            {
                "text": text,
                "page": page,
                "global_idx": global_idx,
                "line_index": line_idx,
                "norm": normalize_strict_text(text),
                "norm_syn": norm_syn,
                "blocked": blocked,
            }
        )

    toc_pages = detect_toc_pages_strict(lines_list)
    if tracer is not None:
        tracer.ev("toc_pages", pages=sorted(toc_pages))

    from collections import defaultdict

    per_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for line in lines:
        if line["blocked"]:
            continue
        per_page[line["page"]].append(line)

    page_positions: Dict[int, Dict[int, int]] = {}
    for page, items in per_page.items():
        sorted_items = sorted(items, key=lambda item: item["global_idx"])
        page_positions[page] = {
            item["global_idx"]: position for position, item in enumerate(sorted_items)
        }

    def in_band(line: Dict[str, Any]) -> bool:
        positions = page_positions.get(line["page"])
        if not positions:
            return False
        pos = positions.get(line["global_idx"])
        if pos is None:
            return False
        band_limit = max(HEADERS_STRICT_BAND_LINES, 0)
        total = len(per_page.get(line["page"], []))
        if band_limit == 0 or total == 0:
            return False
        return pos < band_limit or pos >= max(0, total - band_limit)

    resolved: List[Dict[str, Any]] = []
    prev_idx = -1

    for header in llm_headers:
        title = str(header.get("title") or header.get("text") or "")
        title_norm = normalize_strict_text(title)
        number_value = header.get("number")
        number = str(number_value).strip() if isinstance(number_value, str) else None
        want_full = normalize_strict_text(f"{number} {title}") if number else title_norm
        number_regex = compile_number_regex_fuzzy(number) if number else None

        candidates: List[Tuple[int, Dict[str, Any], str, bool]] = []
        weak_candidates: List[Tuple[int, Dict[str, Any], str, bool]] = []
        if number_regex is not None:
            for line in lines:
                if line["blocked"] or line["page"] in toc_pages:
                    continue
                norm_basis = line["norm_syn"] or line["norm"]
                if number_regex.search(line["norm"]) or (
                    line["norm_syn"] and number_regex.search(line["norm_syn"])
                ):
                    band_flag = in_band(line)
                    raw_score = token_set_ratio(norm_basis, want_full)
                    adjusted_score = raw_score - (10 if band_flag else 0)
                    if adjusted_score >= HEADERS_STRICT_FUZZY_THRESH:
                        candidates.append((adjusted_score, line, "num+title", band_flag))
                    elif adjusted_score > 0:
                        weak_candidates.append((adjusted_score, line, "num+title-weak", band_flag))

        filtered_candidates = candidates
        if HEADERS_STRICT_AFTER_ANCHOR_ONLY and prev_idx >= 0:
            filtered_candidates = [
                candidate for candidate in candidates if candidate[1]["global_idx"] > prev_idx
            ]

        chosen: Optional[Tuple[int, Dict[str, Any], str, bool]] = None
        if filtered_candidates:
            chosen = max(
                filtered_candidates, key=lambda item: (item[0], -item[1]["global_idx"])
            )

        if (
            chosen is None
            and HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK
            and candidates
        ):
            fallback_candidate = max(candidates, key=lambda item: item[1]["global_idx"])
            chosen = (fallback_candidate[0], fallback_candidate[1], "last_occurrence", fallback_candidate[3])

        if chosen is None and weak_candidates:
            weak_filtered = weak_candidates
            if HEADERS_STRICT_AFTER_ANCHOR_ONLY and prev_idx >= 0:
                weak_filtered = [
                    candidate for candidate in weak_candidates if candidate[1]["global_idx"] > prev_idx
                ]
            if weak_filtered:
                chosen = max(
                    weak_filtered, key=lambda item: (item[0], -item[1]["global_idx"])
                )
            elif HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK:
                fallback_candidate = max(weak_candidates, key=lambda item: item[1]["global_idx"])
                chosen = (
                    fallback_candidate[0],
                    fallback_candidate[1],
                    "num+title-weak-last",
                    fallback_candidate[3],
                )

        if chosen is None and title_norm:
            for line in lines:
                if line["blocked"] or line["page"] in toc_pages:
                    continue
                if HEADERS_STRICT_AFTER_ANCHOR_ONLY and line["global_idx"] <= prev_idx:
                    continue
                norm_basis = line["norm_syn"] or line["norm"]
                score = token_set_ratio(norm_basis, title_norm)
                if score >= HEADERS_STRICT_TITLE_ONLY_THRESH:
                    band_flag = in_band(line)
                    chosen = (score, line, "title_only", band_flag)
                    break

        if chosen is None:
            fallback_line = None
            for line in lines:
                if line["blocked"] or line["page"] in toc_pages:
                    continue
                if HEADERS_STRICT_AFTER_ANCHOR_ONLY and line["global_idx"] <= prev_idx:
                    continue
                fallback_line = line
                break
            if fallback_line is not None:
                chosen = (0, fallback_line, "sequential_fallback", False)
            else:
                log.debug("Header not located in body: %s", header.get("text"))
                if tracer is not None:
                    tracer.ev(
                        "anchor_unresolved_strict",
                        number=number,
                        title=title,
                        reason="no_candidate",
                    )
                continue

        score, line, strategy, band_flag = chosen
        prev_idx = line["global_idx"]
        if tracer is not None:
            tracer.ev(
                "candidate_found",
                number=number,
                title=title,
                page=line.get("page"),
                idx=line.get("global_idx"),
                line_index=line.get("line_index"),
                score=score,
                strategy=strategy,
                band=band_flag,
                toc_page=line.get("page") in toc_pages,
            )
        resolved.append(
            {
                "header": header,
                "line": line,
                "number": number,
                "score": score,
                "strategy": strategy,
                "band": band_flag,
            }
        )
        if tracer is not None:
            tracer.ev(
                "anchor_resolved_strict",
                number=number,
                title=title,
                page=line["page"],
                idx=line["global_idx"],
                score=score,
                band=band_flag,
                toc_page=line["page"] in toc_pages,
                strategy=strategy,
                want=want_full,
                text=line["text"][:200],
            )

    if not resolved:
        return []

    resolved.sort(key=lambda item: item["line"]["global_idx"])

    if HEADERS_FINAL_MONOTONIC_GUARD:
        fixed = 0
        position_map: Dict[str, int] = {
            item["number"]: item["line"]["global_idx"]
            for item in resolved
            if item["number"]
        }
        for item in resolved:
            number = item.get("number")
            if not number or "." not in number:
                continue
            parent = ".".join(number.split(".")[:-1])
            parent_idx = position_map.get(parent)
            if parent_idx is None:
                continue
            if parent_idx <= item["line"]["global_idx"]:
                continue
            regex = compile_number_regex_fuzzy(number)
            all_candidates = [
                line
                for line in lines
                if not line["blocked"]
                and line["page"] not in toc_pages
                and (
                    regex.search(line["norm"])
                    or (line["norm_syn"] and regex.search(line["norm_syn"]))
                )
            ]
            after_parent = [
                line for line in all_candidates if line["global_idx"] > parent_idx
            ]
            repick = None
            if after_parent:
                repick = max(after_parent, key=lambda cand: cand["global_idx"])
            elif HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK and all_candidates:
                repick = max(all_candidates, key=lambda cand: cand["global_idx"])
            if repick is not None and repick["global_idx"] != item["line"]["global_idx"]:
                item["line"] = repick
                position_map[number] = repick["global_idx"]
                fixed += 1
                if tracer is not None:
                    tracer.ev(
                        "final_monotonic_fix",
                        number=number,
                        new_idx=repick["global_idx"],
                        parent=parent,
                        parent_idx=parent_idx,
                    )
        if tracer is not None:
            tracer.ev("final_monotonic_pass", fixed=fixed)
        resolved.sort(key=lambda item: item["line"]["global_idx"])

    return resolved


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
            "title": entry.get("title"),
            "number": number,
            "level": _coerce_level(entry.get("level")),
        }


def _align_headers_to_sections(
    llm_headers: Sequence[Dict[str, Any]],
    lines_list: List[BodyLine],
    tracer: HeaderTracer | None,
    *,
    fenced_text: str | None,
) -> Dict[str, Any]:
    if tracer is not None:
        tracer.log_call(f"{__name__}._align_headers_to_sections")

    resolved = align_headers_llm_strict(llm_headers, lines_list, tracer=tracer)

    located: List[Dict[str, Any]] = []
    for item in resolved:
        header = item["header"]
        line = item["line"]
        if not lines_list:
            continue
        line_index = line.get("line_index", 0)
        try:
            line_index = int(line_index)
        except Exception:
            line_index = 0
        if not (0 <= line_index < len(lines_list)):
            fallback_index = next(
                (
                    idx
                    for idx, original in enumerate(lines_list)
                    if int(original.get("global_idx", idx) or idx) == line["global_idx"]
                ),
                None,
            )
            if fallback_index is not None:
                line_index = fallback_index
            else:
                line_index = max(0, min(len(lines_list) - 1, line_index))
        located.append(
            {
                "text": header.get("text", ""),
                "number": header.get("number"),
                "level": header.get("level"),
                "line_index": line_index,
                "start_global_index": line["global_idx"],
                "start_page": line["page"],
            }
        )

    located.sort(key=lambda item: item["start_global_index"])

    sections: List[Dict[str, Any]] = []
    if lines_list and located:
        for idx, header in enumerate(located):
            start_line_index = header["line_index"]
            if idx + 1 < len(located):
                next_line_index = located[idx + 1]["line_index"] - 1
            else:
                next_line_index = len(lines_list) - 1
            if next_line_index < start_line_index:
                next_line_index = start_line_index
            end_line = lines_list[next_line_index]
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
        "fenced_text": fenced_text,
    }


class _SupportsGenerate:
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

    if tracer is not None:
        tracer.log_call(f"{__name__}.extract_headers_and_sections_strict")

    lines_list = list(lines)
    full_text = "\n".join(str(line.get("text", "")) for line in lines_list)

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
    if tracer is not None:
        tracer.ev(
            "llm_outline_received",
            count=len(llm_headers),
            headers=[{**header} for header in llm_headers],
        )

    return _align_headers_to_sections(
        llm_headers,
        lines_list,
        tracer,
        fenced_text=result.fenced,
    )


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def run_strict_headers_pipeline(
    *,
    file_id: int,
    file_path: str | os.PathLike[str],
    provider: str,
    model: str,
    trace: bool = False,
) -> Dict[str, Any]:
    """Legacy orchestration wrapper used by guard-rail tests."""

    from ..services import llm as llm_module
    from ..services import text_extraction
    from ..config import get_settings
    from .llm import LLMService

    lines_list = list(text_extraction.extract_lines(str(file_path)))
    if not lines_list:
        if _env_flag("HEADERS_STRICT_ABORT_ON_NO_LINES", "0"):
            raise AlignmentPreconditionError(
                "no_lines",
                "No lines available for strict header alignment.",
                {"file_id": file_id},
            )
        return {"headers": [], "sections": [], "fenced_text": None}

    fail_on_empty = _env_flag("HEADERS_STRICT_FAIL_ON_EMPTY_OUTLINE", "0")

    tracer: HeaderTracer | None = None
    settings = get_settings()
    if trace and HeaderTracer is not None:
        tracer = HeaderTracer(out_dir=str(settings.headers_log_dir))
        tracer.ev(
            "start_run",
            mode="llm_strict",
            file_id=file_id,
            metadata={"provider": provider, "model": model},
        )

    if tracer is not None:
        tracer.log_call(f"{__name__}.run_strict_headers_pipeline")

    outline_loader = getattr(llm_module, "get_outline_for_headers", None)
    if callable(outline_loader):
        outline_raw = outline_loader(
            file_id=file_id,
            file_path=str(file_path),
            provider=provider,
            model=model,
            trace=trace,
            lines=lines_list,
        )
        outline_text = str(outline_raw or "").strip()
        if not outline_text:
            if fail_on_empty:
                raise OutlineParseError(
                    "empty_outline",
                    "LLM outline was empty.",
                    raw=str(outline_raw or ""),
                )
            return {"headers": [], "sections": [], "fenced_text": None}

        try:
            payload = json.loads(outline_text)
        except json.JSONDecodeError as exc:
            raise OutlineParseError(
                "invalid_outline",
                "LLM outline could not be decoded as JSON.",
                raw=outline_text,
            ) from exc

        llm_headers = list(_extract_headers(payload))
        if tracer is not None:
            tracer.ev(
                "llm_outline_received",
                count=len(llm_headers),
                headers=[{**header} for header in llm_headers],
            )
        if not llm_headers:
            if fail_on_empty:
                raise OutlineParseError(
                    "empty_outline",
                    "LLM outline did not contain any headers.",
                    raw=outline_text,
                )
            return {"headers": [], "sections": [], "fenced_text": outline_text}

        return _align_headers_to_sections(
            llm_headers,
            lines_list,
            tracer,
            fenced_text=outline_text,
        )

    llm_service = LLMService(settings=settings)
    return extract_headers_and_sections_strict(
        llm=llm_service,
        lines=lines_list,
        tracer=tracer,
    )


__all__ = [
    "extract_headers_and_sections_strict",
    "align_headers_llm_strict",
    "run_strict_headers_pipeline",
    "FENCE",
]
