"""Locate LLM derived headers within parsed line metrics."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Sequence

from ..utils.trace import HeaderTracer


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def locate_headers_in_lines(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    excluded_pages: Iterable[int] = (),
    similarity_threshold: float = 0.88,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    """Return located headers with page and line metadata."""

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


__all__ = ["locate_headers_in_lines"]
