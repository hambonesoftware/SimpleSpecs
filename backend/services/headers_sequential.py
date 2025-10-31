"""Sequential alignment strategy for mapping LLM headers to PDF lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from rapidfuzz.fuzz import token_set_ratio

from backend.config import (
    HEADERS_SUPPRESS_TOC,
    HEADERS_SUPPRESS_RUNNING,
    HEADERS_FUZZY_THRESHOLD,
    HEADERS_NORMALIZE_CONFUSABLES,
    HEADERS_WINDOW_PAD_LINES,
    HEADERS_BAND_LINES,
    HEADERS_L1_REQUIRE_NUMERIC,
    HEADERS_L1_LOOKAHEAD_CHILD_HINT,
    HEADERS_MONOTONIC_STRICT,
    HEADERS_REANCHOR_PASS,
)

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


def detect_running_header_footer(lines: List[Line], band: int | None = None) -> set[str]:
    from collections import Counter, defaultdict

    limit = HEADERS_BAND_LINES if band is None else band
    if limit <= 0:
        return set()

    per_page: Dict[int, List[Line]] = defaultdict(list)
    for entry in lines:
        per_page[entry.page].append(entry)

    occurrences = Counter()
    total_pages = len(per_page)
    for page_lines in per_page.values():
        ordered = sorted(page_lines, key=lambda line: line.global_idx)
        tops = ordered[:limit]
        bots = ordered[-limit:] if len(ordered) >= limit else ordered[-len(ordered):]
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
    items.sort(key=lambda item: ([int(part) for part in item.num.split(".")], item.level))
    return items


def page_positions(lines: List[Line]) -> Dict[int, Dict[int, int]]:
    """Return mapping of page -> {global_idx -> position_on_page}."""

    from collections import defaultdict

    per_page: Dict[int, List[Line]] = defaultdict(list)
    for ln in lines:
        per_page[ln.page].append(ln)
    mapping: Dict[int, Dict[int, int]] = {}
    for page, page_lines in per_page.items():
        ordered = sorted(page_lines, key=lambda line: line.global_idx)
        mapping[page] = {line.global_idx: idx for idx, line in enumerate(ordered)}
    return mapping


def in_page_band(ln: Line, pos_map: Dict[int, Dict[int, int]], band: int) -> bool:
    positions = pos_map.get(ln.page, {})
    if not positions:
        return False
    pos = positions.get(ln.global_idx)
    if pos is None:
        return False
    count = len(positions)
    return pos < band or pos >= max(0, count - band)


def has_child_hint(
    lines: List[Line],
    idx: int,
    parent_num: str,
    confusables: bool,
    lookahead: int,
    runners: set[str],
    toc_pages: set[int],
) -> bool:
    if lookahead <= 0:
        return False
    hint_pattern = re.compile(rf"^\s*{re.escape(parent_num)}\.\d+", re.I)
    end = min(len(lines), idx + 1 + lookahead)
    for offset in range(idx + 1, end):
        candidate = lines[offset]
        if candidate.page in toc_pages:
            continue
        norm = normalize(candidate.text, confusables=confusables)
        if norm in runners:
            continue
        if hint_pattern.search(candidate.text):
            return True
    return False


def score_l1_candidate(
    lines: List[Line],
    idx: int,
    want_num: str,
    want_title_norm: str,
    confusables: bool,
    pos_map: Dict[int, Dict[int, int]],
    runners: set[str],
    toc_pages: set[int],
) -> Tuple[int, str]:
    line = lines[idx]
    if line.page in toc_pages:
        return (-999, "toc_page")
    norm = normalize(line.text, confusables=confusables)
    if norm in runners:
        return (-999, "runner_text")

    has_num = bool(compile_number_regex(want_num).search(norm))
    text_score = token_set_ratio(norm, want_title_norm)
    score = text_score
    reason = "text_only"
    if has_num:
        score += 25
        reason = "numeric+text"
    if in_page_band(line, pos_map, HEADERS_BAND_LINES):
        score -= 20
        reason += "|band_penalty"
    if has_child_hint(
        lines,
        idx,
        want_num,
        confusables,
        HEADERS_L1_LOOKAHEAD_CHILD_HINT,
        runners,
        toc_pages,
    ):
        score += 5
        reason += "|child_hint"
    return (score, reason)


def find_later_duplicate(
    lines: List[Line],
    start_idx: int,
    text_norm: str,
    confusables: bool,
    toc_pages: set[int],
    runners: set[str],
) -> Optional[int]:
    for idx in range(start_idx + 1, len(lines)):
        line = lines[idx]
        if line.page in toc_pages:
            continue
        norm = normalize(line.text, confusables=confusables)
        if norm in runners:
            continue
        if norm == text_norm:
            return idx
    return None


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
    cursor_idx = -1
    pos_map = page_positions(lines)

    for item in tops:
        want_title_norm = normalize(f"{item.num} {item.title}", confusables=confusables)
        best_idx: Optional[int] = None
        best_score = -999
        best_reason = ""
        passes = (1, 2) if HEADERS_L1_REQUIRE_NUMERIC else (2,)
        for pass_id in passes:
            for idx in range(cursor_idx + 1, len(lines)):
                score, reason = score_l1_candidate(
                    lines,
                    idx,
                    item.num,
                    want_title_norm,
                    confusables,
                    pos_map,
                    runners,
                    toc_pages,
                )
                if pass_id == 1 and "numeric" not in reason:
                    continue
                if HEADERS_MONOTONIC_STRICT and cursor_idx >= 0 and idx <= cursor_idx:
                    if tracer:
                        tracer.ev(
                            "monotonic_reject",
                            num=item.num,
                            idx=lines[idx].global_idx,
                            cursor=lines[cursor_idx].global_idx if cursor_idx >= 0 else -1,
                            reason="l1_before_cursor",
                        )
                    continue
                if score > best_score:
                    best_score = score
                    best_idx = idx
                    best_reason = reason
            if best_idx is not None:
                break

        if best_idx is not None:
            chosen = lines[best_idx]
            if HEADERS_MONOTONIC_STRICT and cursor_idx >= 0 and chosen.global_idx <= lines[cursor_idx].global_idx:
                later = find_later_duplicate(
                    lines,
                    best_idx,
                    normalize(chosen.text, confusables=confusables),
                    confusables,
                    toc_pages,
                    runners,
                )
                if later is not None:
                    anchors[item.num] = later
                    cursor_idx = later
                    if tracer:
                        tracer.ev(
                            "later_duplicate_used",
                            num=item.num,
                            from_idx=chosen.global_idx,
                            to_idx=lines[later].global_idx,
                        )
                else:
                    if tracer:
                        tracer.ev("anchor_unresolved_top", num=item.num, reason="no_later_dup")
                    continue
            else:
                anchors[item.num] = best_idx
                cursor_idx = best_idx
            if tracer:
                tracer.ev(
                    "anchor_resolved_top",
                    num=item.num,
                    idx=lines[anchors[item.num]].global_idx,
                    reason=best_reason,
                    score=best_score,
                )
        else:
            if tracer:
                tracer.ev("anchor_unresolved_top", num=item.num)

    ordered = sorted(anchors.items(), key=lambda kv: [int(part) for part in kv[0].split(".")])
    windows: Dict[str, Tuple[int, int, int]] = {}
    for pos, (num, idx) in enumerate(ordered):
        start = idx
        end = len(lines)
        if pos + 1 < len(ordered):
            end = ordered[pos + 1][1]
        windows[num] = (idx, start, end)
        if tracer:
            start_gid = lines[start].global_idx if 0 <= start < len(lines) else None
            end_gid = lines[end - 1].global_idx if 0 <= end - 1 < len(lines) else None
            tracer.ev("window_top", num=num, start=start_gid, end=end_gid)
    return windows


def find_in_window(
    lines: List[Line],
    start_idx: int,
    end_idx: int,
    target: HeaderItem,
    confusables: bool,
    runners: set[str],
    toc_pages: set[int],
    threshold: int,
    *,
    tracer: HeaderTracer | None = None,
    pos_map: Optional[Dict[int, Dict[int, int]]] = None,
    cursor_idx: Optional[int] = None,
) -> Optional[int]:
    re_num = compile_number_regex(target.num)
    want = normalize(f"{target.num} {target.title}", confusables=confusables)
    best: Optional[Tuple[int, int]] = None
    scan_start = max(0, start_idx + 1)
    scan_end = min(len(lines), end_idx)
    for idx in range(scan_start, scan_end):
        line = lines[idx]
        if line.page in toc_pages:
            continue
        norm = normalize(line.text, confusables=confusables)
        if norm in runners:
            continue
        if not re_num.search(norm):
            continue
        score = token_set_ratio(norm, want)
        if pos_map and in_page_band(line, pos_map, HEADERS_BAND_LINES):
            score -= 10
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
            if best is None or score > best[0]:
                best = (score, idx)
    if best is not None:
        _, idx = best
        line = lines[idx]
        if (
            cursor_idx is not None
            and HEADERS_MONOTONIC_STRICT
            and idx <= cursor_idx
        ):
            if tracer:
                tracer.ev(
                    "monotonic_reject",
                    num=target.num,
                    idx=line.global_idx,
                    cursor=lines[cursor_idx].global_idx,
                    reason="child_before_cursor",
                )
        else:
            if tracer:
                tracer.ev(
                    "anchor_resolved_child",
                    num=target.num,
                    idx=line.global_idx,
                    page=line.page,
                    score=best[0],
                )
            return idx

    for idx in range(scan_start, scan_end):
        line = lines[idx]
        if line.page in toc_pages:
            continue
        norm = normalize(line.text, confusables=confusables)
        if norm in runners:
            continue
        if re_num.search(norm):
            if (
                cursor_idx is not None
                and HEADERS_MONOTONIC_STRICT
                and idx <= cursor_idx
            ):
                continue
            if tracer:
                tracer.ev(
                    "fallback_number_only",
                    num=target.num,
                    idx=line.global_idx,
                    page=line.page,
                    text=line.text[:200],
                )
            return idx

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
    index_lookup = {line.global_idx: idx for idx, line in enumerate(lines)}

    items = make_header_items(llm_headers)
    if tracer:
        tracer.ev("sequential_start", items=len(items), lines=len(lines))

    toc_pages = detect_toc_pages(lines) if HEADERS_SUPPRESS_TOC else set()
    runners = detect_running_header_footer(lines) if HEADERS_SUPPRESS_RUNNING else set()
    if tracer:
        tracer.ev("toc_pages", pages=sorted(toc_pages))
        tracer.ev("running_headers_detected", count=len(runners))

    pos_map = page_positions(lines)

    tops = [item for item in items if item.level == 1]
    windows = build_top_level_windows(
        lines,
        tops,
        confusables=confusables,
        runners=runners,
        toc_pages=toc_pages,
        tracer=tracer,
    )

    anchors: Dict[str, int] = {}
    results: List[Tuple[int, Dict]] = []

    for num, (anchor_idx, _, end_idx) in windows.items():
        line = lines[anchor_idx]
        item = next((itm for itm in items if itm.num == num), None)
        title = item.title if item else ""
        level = item.level if item else num.count(".") + 1
        anchors[num] = line.global_idx
        results.append(
            (
                line.global_idx,
                {
                    "number": num,
                    "title": title,
                    "level": level,
                    "global_idx": line.global_idx,
                    "page": line.page,
                    "line_idx": line.line_idx,
                },
            )
        )
        windows[num] = (anchor_idx, anchor_idx, end_idx)

    children = [item for item in items if item.level >= 2]
    children.sort(key=lambda h: ([int(part) for part in h.num.split(".")], h.level))

    chain_cursor: Dict[str, int] = {num: idx for num, (idx, _, _) in windows.items()}

    for header in children:
        parent_num = ".".join(header.num.split(".")[:-1])
        if parent_num not in windows:
            if tracer:
                tracer.ev("missing_parent", child=header.num, parent=parent_num)
            continue
        parent_anchor_idx, parent_start, parent_end = windows[parent_num]
        start = max(0, parent_anchor_idx - window_pad)
        end = min(len(lines), parent_end + window_pad)
        cursor_idx = chain_cursor.get(parent_num)
        idx = find_in_window(
            lines,
            start,
            end,
            header,
            confusables=confusables,
            runners=runners,
            toc_pages=toc_pages,
            threshold=threshold,
            tracer=tracer,
            pos_map=pos_map,
            cursor_idx=cursor_idx,
        )
        if idx is None:
            if tracer:
                tracer.ev("unresolved", num=header.num, reason="no_match_in_window")
            continue

        line = lines[idx]
        anchors[header.num] = line.global_idx
        results.append(
            (
                line.global_idx,
                {
                    "number": header.num,
                    "title": header.title,
                    "level": header.level,
                    "global_idx": line.global_idx,
                    "page": line.page,
                    "line_idx": line.line_idx,
                },
            )
        )
        chain_cursor[header.num] = idx
        windows[header.num] = (idx, idx, end)

    if HEADERS_REANCHOR_PASS:
        if tracer:
            tracer.ev("reanchor_pass_begin")
        from collections import defaultdict

        children_by_parent: Dict[str, List[int]] = defaultdict(list)
        for num, gidx in anchors.items():
            if "." in num:
                parent = ".".join(num.split(".")[:-1])
                children_by_parent[parent].append(gidx)
        for parent, child_positions in children_by_parent.items():
            if parent not in anchors or not child_positions:
                continue
            parent_idx_global = anchors[parent]
            earliest_child_global = min(child_positions)
            if parent_idx_global <= earliest_child_global:
                continue
            parent_item = next((itm for itm in items if itm.num == parent), None)
            if parent_item is None:
                continue
            want_title_norm = normalize(
                f"{parent_item.num} {parent_item.title}", confusables=confusables
            )
            number_regex = compile_number_regex(parent_item.num)
            earliest_child_idx = index_lookup.get(earliest_child_global)
            if earliest_child_idx is None:
                continue
            start_scan = max(0, earliest_child_idx - window_pad * 3)
            new_idx: Optional[int] = None
            for idx in range(start_scan, earliest_child_idx):
                line = lines[idx]
                if line.page in toc_pages:
                    continue
                norm = normalize(line.text, confusables=confusables)
                if norm in runners:
                    continue
                if not number_regex.search(norm):
                    continue
                score = token_set_ratio(norm, want_title_norm) + 25
                if score >= max(HEADERS_FUZZY_THRESHOLD, threshold):
                    new_idx = idx
                    break
            if new_idx is not None:
                new_line = lines[new_idx]
                anchors[parent] = new_line.global_idx
                for pos, (gidx, payload) in enumerate(results):
                    if payload.get("number") == parent:
                        results[pos] = (
                            new_line.global_idx,
                            {
                                **payload,
                                "global_idx": new_line.global_idx,
                                "page": new_line.page,
                                "line_idx": new_line.line_idx,
                            },
                        )
                        break
                if tracer:
                    tracer.ev(
                        "reanchor_parent",
                        num=parent,
                        from_idx=parent_idx_global,
                        to_idx=new_line.global_idx,
                    )
        if tracer:
            tracer.ev("reanchor_pass_end")

    results.sort(key=lambda item: item[0])
    ordered = [payload for _, payload in results]
    if tracer:
        tracer.ev("sequential_end", resolved=len(ordered))
    return ordered


__all__ = ["align_headers_sequential", "normalize"]
