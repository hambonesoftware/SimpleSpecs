from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Set, Tuple

import re

from rapidfuzz.fuzz import token_set_ratio

from backend.config import (
    HEADERS_AFTER_ANCHOR_ONLY,
    HEADERS_BAND_LINES,
    HEADERS_FUZZY_NUMTITLE,
    HEADERS_FUZZY_TITLE_ONLY,
    HEADERS_LAST_OCCURRENCE_FALLBACK,
    HEADERS_PENALTY_BAND,
    HEADERS_PENALTY_TOC,
    HEADERS_RUNNER_MIN_PAGES,
    HEADERS_TOC_MIN_DOT_LEADERS,
    HEADERS_TOC_MIN_SECTION_TOKENS,
    HEADERS_W_FUZZY,
    HEADERS_W_POS,
    HEADERS_W_TYPO,
    HEADERS_FINAL_MONOTONIC_GUARD,
)

try:
    from backend.utils.trace import HeaderTracer
except Exception:  # pragma: no cover - trace optional in tests
    HeaderTracer = None  # type: ignore[assignment]

DOTS = r"[.\u2024\u2027·]"
DOTTED_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
SECTION_LIKE_RE = re.compile(r"^\s*\d+(?:\s*" + DOTS + r"\s*\d+)*\b")
APPENDIX_LINE_RE = re.compile(r"^\s*APPENDIX\s+[A-Z]\b", re.IGNORECASE)


Line = Dict[str, object]
Header = Dict[str, object]


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _compile_num_regex(number: str) -> re.Pattern[str]:
    number_pattern = re.escape(number).replace(r"\.", r"\s*" + DOTS + r"\s*")
    return re.compile(r"^\s*" + number_pattern + r"\b(?!\.)", re.IGNORECASE)


def _two_line_appendix_fuse(lines: Sequence[Line]) -> List[Line]:
    fused: List[Line] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        text = str(current.get("text", ""))
        if APPENDIX_LINE_RE.match(text):
            if index + 1 < len(lines):
                nxt = lines[index + 1]
                nxt_text = str(nxt.get("text", ""))
                if nxt_text.strip():
                    combined = f"{text} {nxt_text}".strip()
                    updated = dict(current)
                    updated["_synthetic_text"] = combined
                    fused.append(updated)
                    index += 2
                    continue
        fused.append(current)
        index += 1
    return fused


def detect_toc_pages(lines: Sequence[Line]) -> Set[int]:
    by_page: Dict[int, List[str]] = defaultdict(list)
    for line in lines:
        by_page[int(line.get("page", 0) or 0)].append(str(line.get("text", "")))
    toc: Set[int] = set()
    for page, texts in by_page.items():
        dots = sum(1 for text in texts if DOTTED_LEADER_RE.search(text))
        sections = sum(1 for text in texts if SECTION_LIKE_RE.search(_norm(text)))
        if dots >= HEADERS_TOC_MIN_DOT_LEADERS or sections >= HEADERS_TOC_MIN_SECTION_TOKENS:
            toc.add(page)
    return toc


def detect_running_headers(lines: Sequence[Line]) -> Set[str]:
    per_page: Dict[int, List[Line]] = defaultdict(list)
    for line in lines:
        per_page[int(line.get("page", 0) or 0)].append(line)
    signatures: Dict[str, int] = defaultdict(int)
    for entries in per_page.values():
        sorted_entries = sorted(entries, key=lambda item: int(item.get("global_idx", 0) or 0))
        top_band = sorted_entries[: HEADERS_BAND_LINES]
        bottom_band = sorted_entries[-HEADERS_BAND_LINES :]
        for candidate in top_band + bottom_band:
            signatures[_norm(str(candidate.get("text", "")))] += 1
    return {text for text, count in signatures.items() if count >= HEADERS_RUNNER_MIN_PAGES and len(text) >= 6}


def _typography_score(line: Line, median_size: float) -> float:
    font_size = float(line.get("font_size") or 0.0)
    bold = 1.0 if line.get("bold") else 0.0
    bonus = 1.0 if font_size >= max(12.0, median_size * 1.1) else 0.0
    return bold + bonus


def _page_positions(lines: Sequence[Line]) -> Dict[int, Dict[int, int]]:
    per_page: Dict[int, List[Line]] = defaultdict(list)
    for line in lines:
        per_page[int(line.get("page", 0) or 0)].append(line)
    lookup: Dict[int, Dict[int, int]] = {}
    for page, entries in per_page.items():
        sorted_entries = sorted(entries, key=lambda item: int(item.get("global_idx", 0) or 0))
        lookup[page] = {
            int(entry.get("global_idx", 0) or 0): position for position, entry in enumerate(sorted_entries)
        }
    return lookup


def _in_band(line: Line, positions: Dict[int, Dict[int, int]]) -> bool:
    page = int(line.get("page", 0) or 0)
    idx = int(line.get("global_idx", 0) or 0)
    page_map = positions.get(page, {})
    if idx not in page_map:
        return False
    position = page_map[idx]
    total = len(page_map)
    return position < HEADERS_BAND_LINES or position >= max(0, total - HEADERS_BAND_LINES)


def align_headers_best(
    llm_headers: Sequence[Header],
    lines_input: Sequence[Line],
    tracer: HeaderTracer | None = None,
) -> List[Dict[str, object]]:
    if tracer:
        tracer.log_call(f"{__name__}.align_headers_best")

    lines = _two_line_appendix_fuse(list(lines_input))
    sizes = [float(line.get("font_size") or 0.0) for line in lines if line.get("font_size") is not None]
    median_size = sorted(sizes)[len(sizes) // 2] if sizes else 0.0

    positions = _page_positions(lines)
    toc_pages = detect_toc_pages(lines)
    running_headers = detect_running_headers(lines)
    if tracer:
        tracer.ev("toc_pages", pages=sorted(toc_pages))
        tracer.ev("running_headers", n=len(running_headers))

    anchors: Dict[str, int] = {}
    prev_idx = -1

    def level_of(number: str) -> int:
        return number.count(".") + 1

    def parent_of(number: str) -> Optional[str]:
        if "." in number:
            return number.rsplit(".", 1)[0]
        return None

    windows: Dict[str, Tuple[int, int]] = {}

    for header in llm_headers:
        number = (header.get("number") or "").strip()
        if not number:
            continue
        title = str(header.get("title") or header.get("text") or "")
        want_full = _norm(f"{number} {title}")
        want_title = _norm(title)
        number_regex = _compile_num_regex(number)

        parent = parent_of(number)
        window_start = prev_idx + 1
        window_end = int(lines[-1].get("global_idx", 0) or 0) + 1 if lines else 0
        if parent and parent in anchors:
            window_start = max(window_start, anchors[parent] + 1)
        if parent and parent in windows:
            window_start, window_end = windows[parent]

        candidates: List[Tuple[float, Line, str]] = []
        for line in lines:
            global_idx = int(line.get("global_idx", 0) or 0)
            if HEADERS_AFTER_ANCHOR_ONLY and global_idx <= prev_idx:
                continue
            text = str(line.get("_synthetic_text") or line.get("text") or "")
            norm_text = _norm(text)
            in_toc = int(line.get("page", 0) or 0) in toc_pages
            has_number = bool(number_regex.search(norm_text))
            fuzzy = token_set_ratio(norm_text, want_full if has_number else want_title)
            typo_score = _typography_score(line, median_size)
            band = _in_band(line, positions)

            score = HEADERS_W_FUZZY * fuzzy + HEADERS_W_TYPO * (50 * typo_score) + HEADERS_W_POS * (0 if band else 50)
            if band:
                score -= HEADERS_PENALTY_BAND
            if in_toc:
                score -= HEADERS_PENALTY_TOC
            if _norm(str(line.get("text", ""))) in running_headers:
                score -= 500

            strategy = "num+title" if has_number else "title_only"
            in_window = window_start <= global_idx < window_end
            if in_window:
                score += 5

            threshold = HEADERS_FUZZY_NUMTITLE if has_number else HEADERS_FUZZY_TITLE_ONLY
            if fuzzy >= threshold:
                candidates.append((score, line, strategy))
                if tracer:
                    tracer.ev(
                        "candidate_found",
                        number=number,
                        idx=global_idx,
                        page=int(line.get("page", 0) or 0),
                        fuzzy=fuzzy,
                        score=score,
                        strategy=strategy,
                        band=band,
                        toc=in_toc,
                        in_window=in_window,
                    )

        chosen: Optional[Tuple[float, Line, str]] = None
        if candidates:
            in_window_candidates = [candidate for candidate in candidates if window_start <= int(candidate[1].get("global_idx", 0) or 0) < window_end]
            pool = in_window_candidates or candidates
            chosen = max(pool, key=lambda item: (item[0], int(item[1].get("global_idx", 0) or 0)))

        if not chosen and HEADERS_LAST_OCCURRENCE_FALLBACK:
            outside_toc = [candidate for candidate in candidates if int(candidate[1].get("page", 0) or 0) not in toc_pages]
            if outside_toc:
                chosen = max(outside_toc, key=lambda item: int(item[1].get("global_idx", 0) or 0))
                chosen = (chosen[0], chosen[1], "last_occurrence")

        if chosen:
            score, line, strategy = chosen
            global_idx = int(line.get("global_idx", 0) or 0)
            anchors[number] = global_idx
            prev_idx = global_idx
            if tracer:
                tracer.ev(
                    "anchor_resolved_best",
                    number=number,
                    idx=global_idx,
                    page=int(line.get("page", 0) or 0),
                    score=score,
                    strategy=strategy,
                    text=str(line.get("text", ""))[:200],
                )
        else:
            if tracer:
                tracer.ev("anchor_unresolved_best", number=number, reason="no_candidate")

        if level_of(number) == 1 and number in anchors:
            window_end = int(lines[-1].get("global_idx", 0) or 0) + 1 if lines else anchors[number] + 1
            windows[number] = (anchors[number], window_end)

    top_level = sorted(
        [number for number in anchors if number.count(".") == 0],
        key=lambda value: [int(part) for part in value.split(".") if part.isdigit()],
    )
    if lines:
        final_idx = int(lines[-1].get("global_idx", 0) or 0) + 1
    else:
        final_idx = 0
    for index, number in enumerate(top_level):
        start = anchors[number]
        end = final_idx
        if index + 1 < len(top_level):
            end = anchors[top_level[index + 1]]
        windows[number] = (start, end)

    def parent(number: str) -> Optional[str]:
        if "." in number:
            return number.rsplit(".", 1)[0]
        return None

    changed = True
    while changed:
        changed = False
        by_parent: Dict[str, List[str]] = defaultdict(list)
        for number in anchors:
            p = parent(number)
            if p:
                by_parent[p].append(number)
        for p, children in by_parent.items():
            if p not in anchors:
                continue
            child_positions = [anchors[child] for child in children if child in anchors]
            if not child_positions:
                continue
            earliest_child = min(child_positions)
            if anchors[p] > earliest_child:
                regex = _compile_num_regex(p)
                candidates = [
                    line
                    for line in lines
                    if int(line.get("global_idx", 0) or 0) < earliest_child
                    and regex.search(
                        _norm(
                            str(line.get("_synthetic_text") or line.get("text") or "")
                        )
                    )
                    and int(line.get("page", 0) or 0) not in toc_pages
                ]
                if candidates:
                    best_parent = max(
                        candidates, key=lambda line: int(line.get("global_idx", 0) or 0)
                    )
                    anchors[p] = int(best_parent.get("global_idx", 0) or 0)
                    changed = True
                    if tracer:
                        tracer.ev(
                            "reanchor_parent_best",
                            parent=p,
                            to_idx=anchors[p],
                            page=int(best_parent.get("page", 0) or 0),
                        )
        for number, global_idx in list(anchors.items()):
            p = parent(number)
            if not p or p not in windows:
                continue
            window_start, window_end = windows[p]
            if global_idx < window_start or global_idx >= window_end:
                regex = _compile_num_regex(number)
                best_line: Optional[Line] = None
                for line in lines:
                    candidate_idx = int(line.get("global_idx", 0) or 0)
                    if not (window_start <= candidate_idx < window_end):
                        continue
                    text = str(line.get("_synthetic_text") or line.get("text") or "")
                    if regex.search(_norm(text)):
                        best_line = line
                        break
                if best_line:
                    anchors[number] = int(best_line.get("global_idx", 0) or 0)
                    changed = True
                    if tracer:
                        tracer.ev(
                            "child_relocate_best",
                            number=number,
                            parent=p,
                            to_idx=anchors[number],
                        )
        deduped: Dict[str, int] = {}
        for number in sorted(anchors, key=lambda key: (key, anchors[key])):
            if number not in deduped:
                deduped[number] = anchors[number]
            else:
                changed = True
                if tracer:
                    tracer.ev(
                        "dedupe_drop_best",
                        number=number,
                        drop_idx=anchors[number],
                        keep_idx=deduped[number],
                    )
        anchors = deduped

    results: List[Dict[str, object]] = []
    for number, idx in anchors.items():
        line = next((entry for entry in lines if int(entry.get("global_idx", 0) or 0) == idx), None)
        header_meta = next(
            (
                header
                for header in llm_headers
                if (header.get("number") or "").strip() == number
            ),
            {},
        )
        results.append(
            {
                "number": number,
                "title": str(header_meta.get("title") or header_meta.get("text") or ""),
                "level": int(header_meta.get("level") or 1),
                "global_idx": idx,
                "page": int(line.get("page", 0) or 0) if line else None,
                "line_idx": int(line.get("line_idx", 0) or 0) if line else 0,
            }
        )

    if HEADERS_FINAL_MONOTONIC_GUARD:
        results.sort(key=lambda item: item["global_idx"])
        positions = {entry["number"]: entry["global_idx"] for entry in results}
        fixes = 0
        for entry in results:
            number = entry["number"]
            p = parent(number)
            if not p or p not in positions:
                continue
            if entry["global_idx"] > positions[number]:
                positions[number] = entry["global_idx"]
            if positions[p] <= entry["global_idx"]:
                continue
            regex = _compile_num_regex(number)
            candidates = [
                line
                for line in lines
                if int(line.get("global_idx", 0) or 0) > positions[p]
                and regex.search(_norm(str(line.get("_synthetic_text") or line.get("text") or "")))
                and int(line.get("page", 0) or 0) not in toc_pages
            ]
            if candidates:
                replacement = min(candidates, key=lambda line: int(line.get("global_idx", 0) or 0))
                entry["global_idx"] = int(replacement.get("global_idx", 0) or 0)
                entry["page"] = int(replacement.get("page", 0) or 0)
                entry["line_idx"] = int(replacement.get("line_idx", 0) or 0)
                positions[number] = entry["global_idx"]
                fixes += 1
                if tracer:
                    tracer.ev(
                        "final_monotonic_fix_best",
                        number=number,
                        new_idx=entry["global_idx"],
                        parent=p,
                    )
        if tracer:
            tracer.ev("final_monotonic_pass_best", fixed=fixes)

    results.sort(key=lambda item: item["global_idx"])
    return results


__all__ = ["align_headers_best", "detect_toc_pages", "detect_running_headers"]
