"""Sequential alignment strategy for mapping LLM headers to PDF lines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from rapidfuzz.fuzz import token_set_ratio

from backend.config import (
    HEADERS_NORMALIZE_CONFUSABLES,
    HEADERS_SUPPRESS_TOC,
    HEADERS_SUPPRESS_RUNNING,
    HEADERS_FUZZY_THRESHOLD,
    HEADERS_WINDOW_PAD_LINES,
    HEADERS_BAND_LINES,
    HEADERS_L1_REQUIRE_NUMERIC,
    HEADERS_L1_LOOKAHEAD_CHILD_HINT,
    HEADERS_MONOTONIC_STRICT,
    HEADERS_REANCHOR_PASS,
    HEADERS_STRICT_INVARIANTS,
    HEADERS_TITLE_ONLY_REANCHOR,
    HEADERS_RESCAN_PASSES,
    HEADERS_DEDUPE_POLICY,
)

try:  # pragma: no cover - optional dependency for tracing
    from backend.utils.trace import HeaderTracer
except Exception:  # pragma: no cover - tracing is optional in tests
    HeaderTracer = None  # type: ignore


if TYPE_CHECKING:  # pragma: no cover - type hints only
    from backend.config import Settings


NUM_RE = re.compile(r"^\s*(?P<num>(\d+(?:\.\d+)*))\b", re.I)
DOT_SPACE_RE = re.compile(r"(\d)\s*\.\s*(\d)")
MULTISPACE_RE = re.compile(r"\s+")
TOC_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
CONFUSABLE_NUM_RE = re.compile(r"(?<=\d)\s*[Il]\s*(?=[\.\s])")
ALPHA_ONE_RE = re.compile(r"(?<=\b[A-Za-z])\s*[Il](?=\b)")
NUMBER_COMPONENT_RE = re.compile(r"[A-Za-z]+|\d+")


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
    order: int
    tokens: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SequentialAlignmentConfig:
    """Configuration bundle for sequential alignment heuristics."""

    confusables: bool = HEADERS_NORMALIZE_CONFUSABLES
    threshold: int = HEADERS_FUZZY_THRESHOLD
    window_pad: int = HEADERS_WINDOW_PAD_LINES
    suppress_toc: bool = HEADERS_SUPPRESS_TOC
    suppress_running: bool = HEADERS_SUPPRESS_RUNNING
    band_lines: int = HEADERS_BAND_LINES
    l1_require_numeric: bool = HEADERS_L1_REQUIRE_NUMERIC
    l1_lookahead_child_hint: int = HEADERS_L1_LOOKAHEAD_CHILD_HINT
    monotonic_strict: bool = HEADERS_MONOTONIC_STRICT
    reanchor_pass: bool = HEADERS_REANCHOR_PASS
    strict_invariants: bool = HEADERS_STRICT_INVARIANTS
    title_only_reanchor: bool = HEADERS_TITLE_ONLY_REANCHOR
    rescan_passes: int = HEADERS_RESCAN_PASSES
    dedupe_policy: str = HEADERS_DEDUPE_POLICY

    @classmethod
    def from_settings(cls, settings: "Settings") -> "SequentialAlignmentConfig":
        """Build a sequential alignment config from :class:`~backend.config.Settings`."""

        return cls(
            confusables=settings.headers_normalize_confusables,
            threshold=settings.headers_fuzzy_threshold,
            window_pad=settings.headers_window_pad_lines,
            suppress_toc=settings.headers_suppress_toc,
            suppress_running=settings.headers_suppress_running,
            band_lines=settings.headers_band_lines,
            l1_require_numeric=settings.headers_l1_require_numeric,
            l1_lookahead_child_hint=settings.headers_l1_lookahead_child_hint,
            monotonic_strict=settings.headers_monotonic_strict,
            reanchor_pass=settings.headers_reanchor_pass,
            strict_invariants=settings.headers_strict_invariants,
            title_only_reanchor=settings.headers_title_only_reanchor,
            rescan_passes=settings.headers_rescan_passes,
            dedupe_policy=settings.headers_dedupe_policy,
        )


def normalize(value: str, confusables: bool = True) -> str:
    """Return a normalised representation for fuzzy comparisons."""

    cleaned = value.replace("\u00ad", "")
    cleaned = DOT_SPACE_RE.sub(r"\1.\2", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    if confusables:
        cleaned = CONFUSABLE_NUM_RE.sub("1", cleaned)
        cleaned = ALPHA_ONE_RE.sub("1", cleaned)
    return cleaned.strip().casefold()


def number_tokens(num: str | None) -> tuple[str, ...]:
    """Return alphanumeric components that form *num* in document order."""

    if not num:
        return tuple()
    return tuple(NUMBER_COMPONENT_RE.findall(str(num)))


def _alpha_component_value(token: str) -> int:
    total = 0
    for char in token.upper():
        if "A" <= char <= "Z":
            total = total * 26 + (ord(char) - ord("A") + 1)
    return total


def _component_value(token: str) -> int:
    if token.isdigit():
        return int(token)
    if token.isalpha():
        return _alpha_component_value(token)
    digits = re.findall(r"\d+", token)
    if digits:
        return int(digits[0])
    return 0


def number_key(num: str | Sequence[str]) -> List[int]:
    """Return sortable key for a numbering token or sequence of tokens."""

    if isinstance(num, str):
        tokens = number_tokens(num)
    else:
        tokens = tuple(num)
    return [_component_value(token) for token in tokens]


def number_parent(num: str | None) -> str | None:
    """Return the immediate parent numbering token for *num* if available."""

    if not num:
        return None
    if "." in num:
        return num.rsplit(".", 1)[0]
    stripped = num.strip()
    if not stripped:
        return None
    idx = len(stripped)
    while idx > 0 and stripped[idx - 1].isdigit():
        idx -= 1
    if idx <= 0 or idx >= len(stripped):
        return None
    return stripped[:idx]


def is_number_descendant(candidate: str, parent: str | None) -> bool:
    """Return True when *candidate* is a descendant of *parent*."""

    if not parent or not candidate or candidate == parent:
        return False
    current = number_parent(candidate)
    while current:
        if current == parent:
            return True
        current = number_parent(current)
    return False


def extract_number(text: str) -> Optional[str]:
    """Extract a dotted numbering prefix from ``text`` if present."""

    match = NUM_RE.search(text)
    return match.group("num") if match else None


def compile_number_regex(num: str) -> re.Pattern[str]:
    tokens = number_tokens(num)
    if not tokens:
        escaped = re.escape(num)
        return re.compile(rf"(?<!\S){escaped}(?=$|\s|[).:-])", re.I)

    parts: List[str] = []
    for idx, token in enumerate(tokens):
        escaped = re.escape(token)
        if idx == 0:
            parts.append(escaped)
            continue
        prev = tokens[idx - 1]
        if prev.isdigit() and token.isdigit():
            parts.append(rf"\s*\.\s*{escaped}")
        else:
            parts.append(rf"[.\s]*{escaped}")

    core = "".join(parts)
    pattern = rf"(?<!\S){core}(?=$|\s|[).:-])"
    return re.compile(pattern, re.I)


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


def cand_score(norm_line: str, want_norm: str, has_number: bool, in_band: bool) -> int:
    """Return a composite score favouring numeric matches and penalising band hits."""

    score = token_set_ratio(norm_line, want_norm)
    if has_number:
        score += 20
    if in_band:
        score -= 15
    return score
def is_ineligible_runner_or_toc(
    ln: Line, norm_text: str, toc_pages: Set[int], runners: Set[str]
) -> bool:
    if ln.page in toc_pages:
        return True
    if norm_text in runners:
        return True
    return False


def make_header_items(llm_headers: Iterable[Dict]) -> List[HeaderItem]:
    items: List[HeaderItem] = []
    for order, header in enumerate(llm_headers):
        number = header.get("number") or extract_number(str(header.get("text", "")))
        title = str(header.get("title") or header.get("text") or "").strip()
        if not number:
            continue
        tokens = number_tokens(str(number))
        if not tokens:
            continue
        level = int(header.get("level") or len(tokens) or 1)
        items.append(
            HeaderItem(
                num=str(number),
                title=title,
                level=level,
                order=order,
                tokens=tokens,
            )
        )
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


def within(value: int, start: int, end: int) -> bool:
    return start <= value < end


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
    tokens = number_tokens(parent_num)
    if not tokens:
        return False
    pattern_parts: List[str] = []
    for idx, token in enumerate(tokens):
        escaped = re.escape(token)
        if idx == 0:
            pattern_parts.append(escaped)
            continue
        prev = tokens[idx - 1]
        if prev.isdigit() and token.isdigit():
            pattern_parts.append(rf"\.{escaped}")
        else:
            pattern_parts.append(rf"[.\s]*{escaped}")
    pattern = r"^\s*" + "".join(pattern_parts) + r"[.\s]*\d+"
    hint_pattern = re.compile(pattern, re.I)
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
    *,
    band_lines: int,
    lookahead_hint: int,
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
    if in_page_band(line, pos_map, band_lines):
        score -= 20
        reason += "|band_penalty"
    if has_child_hint(
        lines,
        idx,
        want_num,
        confusables,
        lookahead_hint,
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
    config: SequentialAlignmentConfig,
    tracer: HeaderTracer | None = None,
) -> Dict[str, Tuple[int, int, int]]:
    if tracer:
        tracer.log_call(f"{__name__}.build_top_level_windows")

    anchors: Dict[str, int] = {}
    cursor_idx = -1
    pos_map = page_positions(lines)

    for item in tops:
        want_title_norm = normalize(f"{item.num} {item.title}", confusables=confusables)
        best_idx: Optional[int] = None
        best_score = -999
        best_reason = ""
        passes = (1, 2) if config.l1_require_numeric else (2,)
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
                    band_lines=config.band_lines,
                    lookahead_hint=config.l1_lookahead_child_hint,
                )
                if pass_id == 1 and "numeric" not in reason:
                    continue
                if config.monotonic_strict and cursor_idx >= 0 and idx <= cursor_idx:
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
            if config.monotonic_strict and cursor_idx >= 0 and chosen.global_idx <= lines[cursor_idx].global_idx:
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

    ordered: List[Tuple[str, int]] = []
    seen: Set[str] = set()
    for item in tops:
        idx = anchors.get(item.num)
        if idx is None:
            continue
        ordered.append((item.num, idx))
        seen.add(item.num)
    for num, idx in anchors.items():
        if num in seen:
            continue
        ordered.append((num, idx))

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
    config: SequentialAlignmentConfig,
    tracer: HeaderTracer | None = None,
    pos_map: Optional[Dict[int, Dict[int, int]]] = None,
    cursor_idx: Optional[int] = None,
) -> Optional[int]:
    if tracer:
        tracer.log_call(f"{__name__}.find_in_window")

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
        if pos_map and in_page_band(line, pos_map, config.band_lines):
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
        if cursor_idx is not None and config.monotonic_strict and idx <= cursor_idx:
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
            if cursor_idx is not None and config.monotonic_strict and idx <= cursor_idx:
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


def convert_windows_to_global(
    lines: List[Line],
    windows: Dict[str, Tuple[int, int, int]],
) -> Dict[str, Tuple[int, int, int]]:
    if not lines:
        return {}

    last_gid = lines[-1].global_idx
    out: Dict[str, Tuple[int, int, int]] = {}
    for num, (anchor_idx, start_idx, end_idx) in windows.items():
        anchor_line = lines[anchor_idx] if 0 <= anchor_idx < len(lines) else None
        start_line = lines[start_idx] if 0 <= start_idx < len(lines) else anchor_line
        if end_idx <= 0:
            end_gid = last_gid + 1
        else:
            end_pos = min(len(lines) - 1, max(0, end_idx - 1))
            end_gid = lines[end_pos].global_idx + 1
        anchor_gid = (
            anchor_line.global_idx
            if anchor_line is not None
            else start_line.global_idx if start_line is not None else 0
        )
        start_gid = (
            start_line.global_idx
            if start_line is not None
            else anchor_gid
        )
        out[num] = (anchor_gid, start_gid, end_gid)
    return out


def compute_windows_from_anchors_and_children(
    lines: List[Line],
    anchors: Dict[str, int],
    llm_items: List[HeaderItem],
) -> Dict[str, Tuple[int, int, int]]:
    """Return evidence-based windows using resolved anchors and earliest children."""

    if not lines or not anchors:
        return {}

    l1s = sorted([h for h in llm_items if h.level == 1], key=lambda h: h.order)
    children_by_parent: Dict[str, List[int]] = {}
    for h in llm_items:
        if h.level >= 2 and h.num in anchors:
            parent = number_parent(h.num)
            if not parent:
                continue
            children_by_parent.setdefault(parent, []).append(anchors[h.num])

    ordered: List[Tuple[str, int]] = []
    for header in l1s:
        anchor_idx = anchors.get(header.num)
        earliest_child = min(children_by_parent.get(header.num, []), default=None)
        start_idx = anchor_idx if anchor_idx is not None else earliest_child
        if (
            anchor_idx is not None
            and earliest_child is not None
            and anchor_idx > earliest_child
        ):
            start_idx = earliest_child
        if start_idx is not None:
            ordered.append((header.num, start_idx))

    ordered.sort(key=lambda item: item[1])
    if not ordered:
        return {}

    last_idx = lines[-1].global_idx if lines else 0
    windows: Dict[str, Tuple[int, int, int]] = {}
    for pos, (num, start) in enumerate(ordered):
        end = last_idx + 1
        if pos + 1 < len(ordered):
            end = ordered[pos + 1][1]
        anchor_val = anchors.get(num, start)
        windows[num] = (anchor_val, start, end)
    return windows


def enforce_invariants_and_autofix(
    lines: List[Line],
    llm_items: List[HeaderItem],
    anchors: Dict[str, int],
    windows: Dict[str, Tuple[int, int, int]],
    *,
    confusables: bool,
    runners: Set[str],
    toc_pages: Set[int],
    tracer: Optional[HeaderTracer],
    fuzzy_threshold: int,
    config: SequentialAlignmentConfig,
) -> Dict[str, int]:
    """Enforce parent/child invariants and relocate anchors when needed."""

    if not config.strict_invariants:
        return anchors

    items_by_num = {item.num: item for item in llm_items}
    lines_by_idx = {line.global_idx: line for line in lines}
    pos = anchors.copy()
    pos_map = page_positions(lines)

    def reanchor_parent_title_only(parent_num: str, earliest_child_idx: int) -> bool:
        parent_item = items_by_num.get(parent_num)
        if parent_item is None:
            return False
        want_norm = normalize(
            f"{parent_item.num} {parent_item.title}", confusables=confusables
        )
        number_regex = compile_number_regex(parent_item.num)
        start_scan = max(0, earliest_child_idx - 800)
        best: Optional[Tuple[int, int, bool]] = None
        for line in lines:
            if line.global_idx >= earliest_child_idx or line.global_idx < start_scan:
                continue
            norm_text = normalize(line.text, confusables=confusables)
            if is_ineligible_runner_or_toc(line, norm_text, toc_pages, runners):
                continue
            has_num = bool(number_regex.search(norm_text))
            if not has_num and not config.title_only_reanchor:
                continue
            score = cand_score(
                norm_text,
                want_norm,
                has_number=has_num,
                in_band=in_page_band(line, pos_map, config.band_lines),
            )
            if score >= max(fuzzy_threshold, 70):
                candidate = (score, line.global_idx, has_num)
                if best is None or candidate > best:
                    best = candidate
        if best is not None:
            pos[parent_num] = best[1]
            if tracer:
                tracer.ev(
                    "reanchor_parent",
                    num=parent_num,
                    to_idx=best[1],
                    mode="numeric" if best[2] else "title-only",
                )
            return True
        pos[parent_num] = earliest_child_idx
        if tracer:
            tracer.ev(
                "reanchor_parent_implied", num=parent_num, to_idx=earliest_child_idx
            )
        return True

    def parent_children_map() -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = {}
        for item in llm_items:
            if item.level >= 2:
                parent = number_parent(item.num)
                if not parent:
                    continue
                mapping.setdefault(parent, []).append(item.num)
        return mapping

    def dedupe_within_windows() -> None:
        for parent_num, (_, window_start, window_end) in windows.items():
            bucket: Dict[str, List[int]] = {}
            for num, idx in pos.items():
                if not within(idx, window_start, window_end):
                    continue
                if num == parent_num or is_number_descendant(num, parent_num):
                    bucket.setdefault(num, []).append(idx)
            for num, indices in bucket.items():
                if len(indices) <= 1:
                    continue
                chosen_idx = None
                if config.dedupe_policy == "earliest":
                    chosen_idx = min(indices)
                else:
                    item = items_by_num.get(num)
                    want_norm = (
                        normalize(
                            f"{item.num} {item.title}", confusables=confusables
                        )
                        if item
                        else ""
                    )
                    number_regex = compile_number_regex(num)
                    best_score = -999
                    for gi in sorted(indices):
                        line = lines_by_idx.get(gi)
                        if line is None:
                            continue
                        norm_text = normalize(line.text, confusables=confusables)
                        if is_ineligible_runner_or_toc(
                            line, norm_text, toc_pages, runners
                        ):
                            continue
                        has_num = bool(number_regex.search(norm_text))
                        score = cand_score(norm_text, want_norm, has_num, False)
                        if score > best_score or (
                            score == best_score and (chosen_idx is None or gi < chosen_idx)
                        ):
                            best_score = score
                            chosen_idx = gi
                if chosen_idx is None:
                    chosen_idx = min(indices)
                for gi in indices:
                    if gi != chosen_idx and tracer:
                        tracer.ev(
                            "dedupe_drop",
                            num=num,
                            drop_idx=gi,
                            keep_idx=chosen_idx,
                        )
                pos[num] = chosen_idx

    for pass_idx in range(max(1, config.rescan_passes)):
        changed = False
        pc_map = parent_children_map()
        for parent_num, kids in pc_map.items():
            kid_indices = [pos[child] for child in kids if child in pos]
            if not kid_indices:
                continue
            earliest_child_idx = min(kid_indices)
            if parent_num not in pos or pos[parent_num] > earliest_child_idx:
                if reanchor_parent_title_only(parent_num, earliest_child_idx):
                    changed = True

        computed = compute_windows_from_anchors_and_children(lines, pos, llm_items)
        if computed:
            windows.update(computed)

        for parent_num, (_, window_start, window_end) in windows.items():
            for num, idx in list(pos.items()):
                if num == parent_num or not is_number_descendant(num, parent_num):
                    continue
                if within(idx, window_start, window_end):
                    continue
                item = items_by_num.get(num)
                if item is None:
                    continue
                number_regex = compile_number_regex(num)
                want_norm = normalize(
                    f"{item.num} {item.title}", confusables=confusables
                )
                best_idx: Optional[int] = None
                best_score = -999
                for line in lines:
                    if not within(line.global_idx, window_start, window_end):
                        continue
                    norm_text = normalize(line.text, confusables=confusables)
                    if is_ineligible_runner_or_toc(line, norm_text, toc_pages, runners):
                        continue
                    if not number_regex.search(norm_text):
                        continue
                    score = cand_score(
                        norm_text,
                        want_norm,
                        has_number=True,
                        in_band=in_page_band(line, pos_map, config.band_lines),
                    )
                    if score >= fuzzy_threshold and score > best_score:
                        best_score = score
                        best_idx = line.global_idx
                if best_idx is not None:
                    if tracer:
                        tracer.ev(
                            "child_relocate_to_window",
                            num=num,
                            from_idx=idx,
                            to_idx=best_idx,
                            parent=parent_num,
                        )
                    pos[num] = best_idx
                    changed = True

        before = pos.copy()
        dedupe_within_windows()
        if pos != before:
            changed = True

        if tracer:
            tracer.ev("invariants_pass", pass_id=pass_idx, changed=changed, anchors=len(pos))
        if not changed:
            break

    return pos


def align_headers_sequential(
    llm_headers: Iterable[Dict],
    lines_input: Iterable[Dict],
    *,
    config: SequentialAlignmentConfig | None = None,
    confusables: bool | None = None,
    threshold: int | None = None,
    window_pad: int | None = None,
    tracer: HeaderTracer | None = None,
) -> List[Dict]:
    """Return aligned headers with positional metadata using sequential search."""

    if tracer:
        tracer.log_call(f"{__name__}.align_headers_sequential")

    cfg = config or SequentialAlignmentConfig()
    if any(param is not None for param in (confusables, threshold, window_pad)):
        cfg = replace(
            cfg,
            confusables=cfg.confusables if confusables is None else confusables,
            threshold=cfg.threshold if threshold is None else threshold,
            window_pad=cfg.window_pad if window_pad is None else window_pad,
        )

    confusables = cfg.confusables
    threshold = cfg.threshold
    window_pad = cfg.window_pad

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
    items_by_num = {item.num: item for item in items}
    if tracer:
        tracer.ev("sequential_start", items=len(items), lines=len(lines))

    toc_pages = detect_toc_pages(lines) if cfg.suppress_toc else set()
    runners = (
        detect_running_header_footer(lines, cfg.band_lines)
        if cfg.suppress_running
        else set()
    )
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
        config=cfg,
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
    children.sort(key=lambda h: h.order)

    chain_cursor: Dict[str, int] = {num: idx for num, (idx, _, _) in windows.items()}

    for header in children:
        parent_num = number_parent(header.num)
        if not parent_num:
            continue
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
            config=cfg,
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

    if cfg.reanchor_pass:
        if tracer:
            tracer.ev("reanchor_pass_begin")
        from collections import defaultdict

        children_by_parent: Dict[str, List[int]] = defaultdict(list)
        for num, gidx in anchors.items():
            parent = number_parent(num)
            if not parent:
                continue
            children_by_parent[parent].append(gidx)
        for parent, child_positions in children_by_parent.items():
            if parent not in anchors or not child_positions:
                continue
            parent_idx_global = anchors[parent]
            earliest_child_global = min(child_positions)
            if parent_idx_global <= earliest_child_global:
                continue
            parent_item = items_by_num.get(parent)
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
                if score >= max(cfg.threshold, threshold):
                    new_idx = idx
                    break
            if new_idx is not None:
                new_line = lines[new_idx]
                anchors[parent] = new_line.global_idx
                if tracer:
                    tracer.ev(
                        "reanchor_parent",
                        num=parent,
                        from_idx=parent_idx_global,
                        to_idx=new_line.global_idx,
                    )
        if tracer:
            tracer.ev("reanchor_pass_end")

    base_windows = compute_windows_from_anchors_and_children(lines, anchors, items)
    if not base_windows:
        base_windows = convert_windows_to_global(lines, windows)

    anchors = enforce_invariants_and_autofix(
        lines=lines,
        llm_items=items,
        anchors=anchors,
        windows=base_windows,
        confusables=confusables,
        runners=runners,
        toc_pages=toc_pages,
        tracer=tracer,
        fuzzy_threshold=threshold,
        config=cfg,
    )

    line_by_gid = {line.global_idx: line for line in lines}
    order_lookup = {item.num: item.order for item in items}

    ordered: List[Dict] = []
    seen: Set[str] = set()

    for item in items:
        gid = anchors.get(item.num)
        if gid is None:
            continue
        line = line_by_gid.get(gid)
        ordered.append(
            {
                "number": item.num,
                "title": item.title,
                "level": item.level,
                "global_idx": gid,
                "page": line.page if line else None,
                "line_idx": line.line_idx if line else None,
                "source_idx": item.order,
            }
        )
        seen.add(item.num)

    extras: List[Tuple[int, str]] = [
        (gid, num) for num, gid in anchors.items() if num not in seen
    ]
    extras.sort(key=lambda pair: pair[0])

    for gid, num in extras:
        line = line_by_gid.get(gid)
        item = items_by_num.get(num)
        level = item.level if item else num.count(".") + 1
        entry = {
            "number": num,
            "title": item.title if item else "",
            "level": level,
            "global_idx": gid,
            "page": line.page if line else None,
            "line_idx": line.line_idx if line else None,
            "source_idx": order_lookup.get(num, len(order_lookup) + len(ordered)),
        }
        ordered.append(entry)

    if tracer:
        tracer.ev("sequential_end", resolved=len(ordered))
    return ordered


__all__ = ["align_headers_sequential", "normalize", "SequentialAlignmentConfig"]
