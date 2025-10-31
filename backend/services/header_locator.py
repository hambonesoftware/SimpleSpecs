"""Locate LLM derived headers within parsed line metrics."""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Sequence

from backend.config import (
    HEADERS_ALIGN_STRATEGY,
    HEADERS_FUZZY_THRESHOLD,
    HEADERS_NORMALIZE_CONFUSABLES,
    HEADERS_WINDOW_PAD_LINES,
)

from ..utils.trace import HeaderTracer
from .header_align_bp import align_headers_best
from .headers_llm_strict import align_headers_llm_strict
from .headers_sequential import align_headers_sequential


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _locate_headers_legacy(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    excluded_pages: Iterable[int] = (),
    similarity_threshold: float = 0.88,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    excluded = set(excluded_pages)
    usable: list[dict] = []
    for line in lines:
        if line.get("page") in excluded:
            continue
        if line.get("is_running"):
            continue
        copy = dict(line)
        copy["_norm"] = _normalise(str(line.get("text", "")))
        usable.append(copy)

    located: list[Dict] = []
    previous_anchor = -1

    for header in headers:
        target = _normalise(str(header.get("text", "")))
        if not target:
            continue
        number = (header.get("number") or "").strip()
        candidates: list[dict] = []
        if tracer:
            pattern = rf"^\s*{re.escape(number)}" if number else None
            tracer.ev(
                "search_begin",
                target=str(header.get("text", "")),
                number=number or None,
                pattern=pattern,
            )

        for line in usable:
            text = str(line.get("text", ""))
            if number:
                if re.match(rf"^\s*{re.escape(number)}(?:\b|[.)\-\s])", text):
                    candidates.append(line)
                    if tracer:
                        tracer.ev(
                            "candidate_found",
                            target=str(header.get("text", "")),
                            page=int(line.get("page", 0)),
                            line_idx=int(line.get("line_idx", 0)),
                            snippet=text.strip(),
                            score=1.0,
                            before_prev_anchor=int(line.get("global_idx", -1))
                            <= previous_anchor,
                        )
                    continue
            norm = line.get("_norm", "")
            if norm == target or target in norm:
                candidates.append(line)
                if tracer:
                    tracer.ev(
                        "candidate_found",
                        target=str(header.get("text", "")),
                        page=int(line.get("page", 0)),
                        line_idx=int(line.get("line_idx", 0)),
                        snippet=text.strip(),
                        score=1.0,
                        before_prev_anchor=int(line.get("global_idx", -1))
                        <= previous_anchor,
                    )

        if not candidates:
            for line in usable:
                norm = line.get("_norm", "")
                if not norm:
                    continue
                similarity = SequenceMatcher(a=target, b=norm).ratio()
                if similarity >= similarity_threshold:
                    candidates.append(line)
                    if tracer:
                        tracer.ev(
                            "candidate_scored",
                            target=str(header.get("text", "")),
                            page=int(line.get("page", 0)),
                            line_idx=int(line.get("line_idx", 0)),
                            snippet=str(line.get("text", "")).strip(),
                            score=similarity,
                            threshold=similarity_threshold,
                        )

        if not candidates:
            if tracer:
                tracer.ev(
                    "fallback_triggered",
                    method="candidate_search",
                    reason="no_candidates",
                    target=str(header.get("text", "")),
                )
            continue

        best = max(candidates, key=lambda item: item.get("global_idx", -1))
        monotonic_ok = int(best.get("global_idx", -1)) >= previous_anchor
        if tracer and not monotonic_ok:
            tracer.ev(
                "monotonic_violation",
                target=str(header.get("text", "")),
                previous_anchor=previous_anchor,
                candidate_global=int(best.get("global_idx", -1)),
            )
        located.append(
            {
                "text": str(header.get("text", "")).strip(),
                "number": number or None,
                "level": int(header.get("level") or 1),
                "page": int(best.get("page") or 0),
                "line_idx": int(best.get("line_idx") or 0),
                "global_idx": int(best.get("global_idx") or 0),
            }
        )
        previous_anchor = int(best.get("global_idx", -1))
        if tracer:
            tracer.ev(
                "anchor_resolved",
                target=str(header.get("text", "")),
                page=int(best.get("page") or 0),
                line_idx=int(best.get("line_idx") or 0),
                global_idx=previous_anchor,
                monotonic_ok=monotonic_ok,
            )

    located.sort(key=lambda item: item.get("global_idx", 0))
    return located


def locate_headers_in_lines(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    excluded_pages: Iterable[int] = (),
    similarity_threshold: float = 0.88,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    strategy = os.getenv("HEADERS_ALIGN_STRATEGY", HEADERS_ALIGN_STRATEGY).strip().lower()

    if strategy == "best":
        best_headers = align_headers_best(headers, lines, tracer=tracer)

        located: List[Dict] = [
            {
                "text": str(entry.get("title", "")),
                "number": entry.get("number"),
                "level": int(entry.get("level", 1)),
                "page": int(entry.get("page", 0) or 0),
                "line_idx": int(entry.get("line_idx", 0) or 0),
                "global_idx": int(entry.get("global_idx", 0) or 0),
            }
            for entry in best_headers
        ]

        matched_numbers = {
            str(entry.get("number"))
            for entry in best_headers
            if entry.get("number")
        }
        used_indices = {
            int(entry.get("global_idx", 0) or 0)
            for entry in best_headers
        }

        remaining_headers: list[Dict] = []
        for header in headers:
            number = (header.get("number") or "").strip()
            if number and number in matched_numbers:
                continue
            remaining_headers.append(header)

        if remaining_headers:
            filtered_lines = [
                line
                for line in lines
                if int(line.get("global_idx", 0) or 0) not in used_indices
            ]
            legacy = _locate_headers_legacy(
                remaining_headers,
                filtered_lines,
                excluded_pages=excluded_pages,
                similarity_threshold=similarity_threshold,
                tracer=tracer,
            )
            located.extend(legacy)

        located.sort(key=lambda item: item.get("global_idx", 0))
        return located

    if strategy == "strict":
        resolved = align_headers_llm_strict(list(headers), list(lines), tracer=tracer)
        located: List[Dict] = []
        for item in resolved:
            header = item.get("header", {})
            line = item.get("line", {})
            located.append(
                {
                    "text": str(header.get("title") or header.get("text") or ""),
                    "number": header.get("number"),
                    "level": int(header.get("level", 1)),
                    "page": int(line.get("page", 0) or 0),
                    "line_idx": int(line.get("line_index", 0) or 0),
                    "global_idx": int(line.get("global_idx", 0) or 0),
                }
            )
        located.sort(key=lambda item: item.get("global_idx", 0))
        return located

    if strategy == "sequential":
        sequential_headers = align_headers_sequential(
            headers,
            lines,
            confusables=HEADERS_NORMALIZE_CONFUSABLES,
            threshold=HEADERS_FUZZY_THRESHOLD,
            window_pad=HEADERS_WINDOW_PAD_LINES,
            tracer=tracer,
        )

        located: List[Dict] = [
            {
                "text": entry.get("title", ""),
                "number": entry.get("number"),
                "level": int(entry.get("level", 1)),
                "page": int(entry.get("page", 0) or 0),
                "line_idx": int(entry.get("line_idx", 0) or 0),
                "global_idx": int(entry.get("global_idx", 0) or 0),
            }
            for entry in sequential_headers
        ]

        matched_numbers = {str(entry.get("number")) for entry in sequential_headers if entry.get("number")}
        used_indices = {int(entry.get("global_idx", 0) or 0) for entry in sequential_headers}

        remaining_headers: list[Dict] = []
        for header in headers:
            number = (header.get("number") or "").strip()
            if number and number in matched_numbers:
                continue
            remaining_headers.append(header)

        if remaining_headers:
            filtered_lines = [
                line
                for line in lines
                if int(line.get("global_idx", 0) or 0) not in used_indices
            ]
            legacy = _locate_headers_legacy(
                remaining_headers,
                filtered_lines,
                excluded_pages=excluded_pages,
                similarity_threshold=similarity_threshold,
                tracer=tracer,
            )
            located.extend(legacy)

        located.sort(key=lambda item: item.get("global_idx", 0))
        return located

    return _locate_headers_legacy(
        headers,
        lines,
        excluded_pages=excluded_pages,
        similarity_threshold=similarity_threshold,
        tracer=tracer,
    )


__all__ = ["locate_headers_in_lines"]
