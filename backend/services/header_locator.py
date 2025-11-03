"""Locate LLM derived headers within parsed line metrics."""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Sequence

from backend.config import HEADERS_ALIGN_STRATEGY

from ..utils.trace import HeaderTracer
from .headers_sequential import (
    SequentialAlignmentConfig,
    align_headers_sequential,
    compile_number_regex,
    normalize,
)


def _normalise(text: str) -> str:
    return normalize(text, confusables=True)


def _locate_headers_legacy(
    headers: Sequence[Dict],
    lines: Sequence[Dict],
    *,
    excluded_pages: Iterable[int] = (),
    similarity_threshold: float = 0.88,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    excluded = set(excluded_pages)
    if tracer:
        tracer.log_call(f"{__name__}._locate_headers_legacy")
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
        number_pattern = compile_number_regex(number) if number else None
        if tracer:
            pattern = rf"^\s*{re.escape(number)}" if number else None
            tracer.ev(
                "search_begin",
                target=str(header.get("text", "")),
                number=number or None,
                pattern=pattern,
            )

        target_tokens = [token for token in target.split() if token]

        for line in usable:
            text = str(line.get("text", ""))
            norm_text = line.get("_norm", "")
            if number_pattern and (
                number_pattern.search(text) or number_pattern.search(norm_text)
            ):
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
                continue

            if target_tokens and all(token in norm for token in target_tokens):
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

        candidates.sort(key=lambda item: item.get("global_idx", -1))
        best = None
        for candidate in candidates:
            gid = int(candidate.get("global_idx", -1))
            if gid >= previous_anchor:
                best = candidate
                break
        if best is None:
            best = candidates[-1]
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
    strategy: str | None = None,
    sequential_config: SequentialAlignmentConfig | None = None,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    if tracer:
        tracer.log_call(f"{__name__}.locate_headers_in_lines")

    strategy_value = strategy or os.getenv("HEADERS_ALIGN_STRATEGY", HEADERS_ALIGN_STRATEGY)
    strategy_normalised = strategy_value.strip().lower()
    config = sequential_config or SequentialAlignmentConfig()

    index_buckets: dict[tuple[str, str], list[int]] = {}
    for idx, header in enumerate(headers):
        number_key = (header.get("number") or "").strip()
        text_key = _normalise(str(header.get("text", "")))
        index_buckets.setdefault((number_key, text_key), []).append(idx)

    def _take_index(number: str | None, text: str) -> int:
        key = ((number or "").strip(), _normalise(text))
        bucket = index_buckets.get(key)
        if bucket:
            return bucket.pop(0)
        return len(headers) + 1000

    if strategy_normalised == "sequential":
        excluded = {int(page) for page in excluded_pages}

        def _eligible(line: Dict) -> bool:
            page = int(line.get("page", 0) or 0)
            if page in excluded:
                return False
            if line.get("is_toc") or line.get("is_index"):
                return False
            return True

        sequential_lines = [line for line in lines if _eligible(line)]

        sequential_headers = align_headers_sequential(
            headers,
            sequential_lines,
            config=config,
            tracer=tracer,
        )

        total_numbered = sum(1 for header in headers if (header.get("number") or "").strip())
        coverage = (
            len(sequential_headers) / total_numbered
            if total_numbered
            else 1.0
        )
        if coverage < 0.6:
            if tracer:
                tracer.ev(
                    "fallback_triggered",
                    method="sequential",
                    reason="low_coverage",
                    coverage=coverage,
                )
            sequential_headers = []

        located: List[Dict] = [
            {
                "text": entry.get("title", ""),
                "number": entry.get("number"),
                "level": int(entry.get("level", 1)),
                "page": int(entry.get("page", 0) or 0),
                "line_idx": int(entry.get("line_idx", 0) or 0),
                "global_idx": int(entry.get("global_idx", 0) or 0),
                "source_idx": int(entry.get("source_idx", len(headers) + 1000)),
            }
            for entry in sequential_headers
        ]

        for entry in located:
            if entry.get("source_idx", -1) == len(headers) + 1000:
                entry["source_idx"] = _take_index(
                    entry.get("number"), entry.get("text", "")
                )

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
                for line in sequential_lines
                if int(line.get("global_idx", 0) or 0) not in used_indices
            ]
            legacy = _locate_headers_legacy(
                remaining_headers,
                filtered_lines,
                excluded_pages=excluded_pages,
                similarity_threshold=similarity_threshold,
                tracer=tracer,
            )
            for entry in legacy:
                entry["source_idx"] = _take_index(
                    entry.get("number"), entry.get("text", "")
                )
            located.extend(legacy)

        located.sort(
            key=lambda item: (int(item.get("source_idx", len(headers) + 1000)), item.get("global_idx", 0))
        )
        return located

    legacy_only = _locate_headers_legacy(
        headers,
        lines,
        excluded_pages=excluded_pages,
        similarity_threshold=similarity_threshold,
        tracer=tracer,
    )

    for entry in legacy_only:
        entry["source_idx"] = _take_index(entry.get("number"), entry.get("text", ""))

    legacy_only.sort(
        key=lambda item: (int(item.get("source_idx", len(headers) + 1000)), item.get("global_idx", 0))
    )
    return legacy_only


__all__ = ["locate_headers_in_lines"]
