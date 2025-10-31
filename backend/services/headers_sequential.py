"""Sequential alignment strategy for mapping LLM headers to PDF lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from rapidfuzz.fuzz import token_set_ratio

try:  # pragma: no cover - optional dependency for tracing
    from backend.utils.trace import HeaderTracer
except Exception:  # pragma: no cover - tracing is optional in tests
    HeaderTracer = None  # type: ignore

NUM_RE = re.compile(r"^\s*(?P<num>(\d+(?:\.\d+)*))\b", re.I)
DOT_SPACE_RE = re.compile(r"(\d)\s*\.\s*(\d)")
MULTISPACE_RE = re.compile(r"\s+")
TOC_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
CONFUSABLE_NUM_RE = re.compile(r"(?<=\d)\s*[Il]\s*(?=[\.\s])")


@dataclass(slots=True)
class Line:
    """Lightweight container for parsed PDF line metrics."""

    text: str
    page: int
    global_idx: int
    line_idx: int
    is_running: bool = False


@dataclass(slots=True)
class HeaderItem:
    """LLM provided outline entry used for sequential anchoring."""

    num: str
    title: str
    level: int


def normalize(value: str, confusables: bool = True) -> str:
    """Return a normalised representation for fuzzy comparisons."""

    cleaned = value.replace("\u00ad", "")
    cleaned = DOT_SPACE_RE.sub(r"\1.\2", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    if confusables:
        cleaned = CONFUSABLE_NUM_RE.sub("1", cleaned)
    return cleaned.strip().casefold()


def extract_number(text: str) -> Optional[str]:
    """Extract a dotted numbering prefix from ``text`` if present."""

    match = NUM_RE.search(text)
    return match.group("num") if match else None


def compile_number_regex(num: str) -> re.Pattern[str]:
    escaped = re.escape(num)
    return re.compile(rf"^\s*{escaped}\b(?!\.)", re.I)


def is_probable_toc_line(text: str) -> bool:
    return bool(TOC_LEADER_RE.search(text))


def detect_toc_pages(lines: List[Line]) -> set[int]:
    page_hits: Dict[int, int] = {}
    for entry in lines:
        if entry.is_running:
            continue
        if is_probable_toc_line(entry.text):
            page_hits[entry.page] = page_hits.get(entry.page, 0) + 1
    return {page for page, count in page_hits.items() if count >= 6}


def detect_running_header_footer(lines: List[Line], band: int = 2) -> set[str]:
    from collections import Counter, defaultdict

    per_page: Dict[int, List[Line]] = defaultdict(list)
    for entry in lines:
        per_page[entry.page].append(entry)

    occurrences = Counter()
    total_pages = len(per_page)
    for page_lines in per_page.values():
        ordered = sorted(page_lines, key=lambda line: line.global_idx)
        tops = ordered[:band]
        bots = ordered[-band:] if len(ordered) >= band else []
        page_candidates = {
            normalize(candidate.text, confusables=False)
            for candidate in tops + bots
            if not candidate.is_running
        }
        for token in page_candidates:
            occurrences[token] += 1

    threshold = max(2, int(0.6 * total_pages)) if total_pages else 0
    return {text for text, count in occurrences.items() if count >= threshold}


def make_header_items(llm_headers: Iterable[Dict]) -> List[HeaderItem]:
    items: List[HeaderItem] = []
    for header in llm_headers:
        number = header.get("number") or extract_number(str(header.get("text", "")))
        title = str(header.get("title") or header.get("text") or "").strip()
        if not number:
            continue
        level = number.count(".") + 1
        items.append(HeaderItem(num=number, title=title, level=level))
    return items


def build_top_level_windows(
    lines: List[Line],
    tops: List[HeaderItem],
    *,
    confusables: bool,
    runners: set[str],
    toc_pages: set[int],
    tracer: HeaderTracer | None = None,
) -> Dict[str, Tuple[int, int, int]]:
    anchors: Dict[str, int] = {}
    cursor = -1
    line_count = len(lines)

    for item in tops:
        matcher = compile_number_regex(item.num)
        best_idx: Optional[int] = None
        for pos in range(cursor + 1, line_count):
            line = lines[pos]
            if line.page in toc_pages or line.is_running:
                continue
            norm = normalize(line.text, confusables=confusables)
            if norm in runners:
                continue
            if matcher.search(norm):
                score = token_set_ratio(
                    norm, normalize(f"{item.num} {item.title}", confusables=confusables)
                )
                best_idx = pos
                if tracer:
                    tracer.ev(
                        "anchor_candidate_top",
                        num=item.num,
                        page=line.page,
                        idx=line.global_idx,
                        score=score,
                        text=line.text[:200],
                    )
                break
        if best_idx is not None:
            anchors[item.num] = best_idx
            cursor = best_idx
            if tracer:
                tracer.ev(
                    "anchor_resolved_top",
                    num=item.num,
                    idx=lines[best_idx].global_idx,
                )
        elif tracer:
            tracer.ev("anchor_unresolved_top", num=item.num)

    ordered = sorted(anchors.items(), key=lambda entry: [int(part) for part in entry[0].split(".")])
    windows: Dict[str, Tuple[int, int, int]] = {}
    for position, (number, list_idx) in enumerate(ordered):
        start = list_idx
        end = line_count
        if position + 1 < len(ordered):
            end = ordered[position + 1][1]
        windows[number] = (list_idx, start, end)
        if tracer:
            tracer.ev(
                "window_top",
                num=number,
                start=lines[start].global_idx if start < line_count else None,
                end=lines[end - 1].global_idx if end <= line_count and end > 0 else None,
            )
    return windows


def find_in_window(
    lines: List[Line],
    start_pos: int,
    end_pos: int,
    target: HeaderItem,
    *,
    confusables: bool,
    runners: set[str],
    toc_pages: set[int],
    threshold: int,
    tracer: HeaderTracer | None = None,
) -> Optional[int]:
    matcher = compile_number_regex(target.num)
    expected = normalize(f"{target.num} {target.title}", confusables=confusables)
    best: Tuple[int, int] | None = None

    for pos in range(start_pos + 1, min(end_pos, len(lines))):
        line = lines[pos]
        if line.page in toc_pages or line.is_running:
            continue
        norm = normalize(line.text, confusables=confusables)
        if norm in runners:
            continue
        if not matcher.search(norm):
            continue
        score = token_set_ratio(norm, expected)
        if tracer:
            tracer.ev(
                "candidate_found",
                num=target.num,
                idx=line.global_idx,
                page=line.page,
                score=score,
                text=line.text[:200],
            )
        if score >= threshold:
            candidate = (score, pos)
            if best is None or candidate > best:
                best = candidate

    if best is not None:
        _, pos = best
        anchor = lines[pos]
        if tracer:
            tracer.ev(
                "anchor_resolved_child",
                num=target.num,
                idx=anchor.global_idx,
                page=anchor.page,
                score=best[0],
            )
        return pos

    for pos in range(start_pos + 1, min(end_pos, len(lines))):
        line = lines[pos]
        if line.page in toc_pages or line.is_running:
            continue
        norm = normalize(line.text, confusables=confusables)
        if norm in runners:
            continue
        if matcher.search(norm):
            if tracer:
                tracer.ev(
                    "fallback_number_only",
                    num=target.num,
                    idx=line.global_idx,
                    page=line.page,
                    text=line.text[:200],
                )
            return pos

    if tracer:
        tracer.ev("anchor_unresolved_child", num=target.num)
    return None


def align_headers_sequential(
    llm_headers: Iterable[Dict],
    lines_input: Iterable[Dict],
    *,
    confusables: bool = True,
    threshold: int = 80,
    window_pad: int = 40,
    suppress_toc: bool = True,
    suppress_running: bool = True,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    """Return aligned headers with positional metadata using sequential search."""

    lines: List[Line] = []
    for raw in lines_input:
        try:
            line = Line(
                text=str(raw.get("text", "")),
                page=int(raw.get("page", 0)),
                global_idx=int(raw.get("global_idx", 0)),
                line_idx=int(raw.get("line_idx") or raw.get("line_index") or 0),
                is_running=bool(raw.get("is_running")),
            )
        except Exception:
            continue
        lines.append(line)

    lines.sort(key=lambda entry: entry.global_idx)

    items = make_header_items(llm_headers)
    if tracer:
        tracer.ev("sequential_start", items=len(items), lines=len(lines))

    toc_pages = detect_toc_pages(lines) if suppress_toc else set()
    runners = detect_running_header_footer(lines) if suppress_running else set()
    if tracer:
        tracer.ev("toc_pages", pages=sorted(toc_pages))
        tracer.ev("running_headers_detected", count=len(runners))

    item_lookup = {item.num: item for item in items}

    tops = [item for item in items if item.level == 1]
    windows = build_top_level_windows(
        lines,
        tops,
        confusables=confusables,
        runners=runners,
        toc_pages=toc_pages,
        tracer=tracer,
    )

    children = [item for item in items if item.level >= 2]
    children.sort(key=lambda item: [int(part) for part in item.num.split(".")])

    results: Dict[str, Dict] = {}

    for number, (pos, _, _) in windows.items():
        line = lines[pos]
        level = number.count(".") + 1
        results[number] = {
            "number": number,
            "title": item_lookup[number].title if number in item_lookup else "",
            "level": level,
            "global_idx": line.global_idx,
            "page": line.page,
            "line_idx": line.line_idx,
        }

    for child in children:
        parent_num = ".".join(child.num.split(".")[:-1])
        if parent_num not in windows:
            if tracer:
                tracer.ev("missing_parent", child=child.num, parent=parent_num)
            continue
        anchor_pos, parent_start, parent_end = windows[parent_num]
        start = max(0, parent_start - window_pad)
        end = min(len(lines), parent_end + window_pad)
        found_pos = find_in_window(
            lines,
            start,
            end,
            child,
            confusables=confusables,
            runners=runners,
            toc_pages=toc_pages,
            threshold=threshold,
            tracer=tracer,
        )
        if found_pos is None:
            if tracer:
                tracer.ev("unresolved", num=child.num, reason="no_match_in_window")
            continue

        line = lines[found_pos]
        windows[child.num] = (found_pos, found_pos, min(len(lines), parent_end))
        results[child.num] = {
            "number": child.num,
            "title": child.title,
            "level": child.level,
            "global_idx": line.global_idx,
            "page": line.page,
            "line_idx": line.line_idx,
        }

    ordered = sorted(results.values(), key=lambda item: item["global_idx"])
    if tracer:
        tracer.ev("sequential_end", resolved=len(ordered))
    return ordered


__all__ = [
    "align_headers_sequential",
    "normalize",
]
