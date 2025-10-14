"""Header detection heuristics based on layout-aware PDF extraction."""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from ..models import HeaderItem
from .pdf_native import TextLine

logger = logging.getLogger(__name__)

NUMERIC_RE = re.compile(r"^(?:\d+)(?:\.\d+){0,5}\b")
ROMAN_RE = re.compile(r"^(?:[IVXLCDM]+)(?:\.[A-Za-z0-9]+){0,4}\b", re.IGNORECASE)
ALPHA_RE = re.compile(r"^(?:[A-Z])(?:\.[A-Za-z0-9]+){0,4}\b")
DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+$")
TOC_KEYWORDS = {"contents", "table of contents", "toc"}

__all__ = ["HeaderNode", "HeaderDetectionResult", "detect_headers"]


@dataclass
class HeaderNode:
    """Hierarchical node describing a detected header."""

    id: str
    title: str
    level: int
    page: int
    line_index: int
    number: str | None
    score: float
    children: list["HeaderNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "page": self.page,
            "line_index": self.line_index,
            "number": self.number,
            "score": round(self.score, 4),
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class HeaderDetectionResult:
    """Result bundle produced by ``detect_headers``."""

    headers: list[HeaderItem]
    tree: list[HeaderNode]

    def to_dict(self) -> dict[str, object]:
        return {"headers": [item.model_dump() for item in self.headers], "tree": [node.to_dict() for node in self.tree]}


@dataclass
class _Candidate:
    line: TextLine
    score: float
    number: str | None
    title: str
    level: int


def _structured_debug(enabled: bool, event: str, **data: object) -> None:
    if not enabled:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        payload = json.dumps({key: repr(value) for key, value in data.items()}, ensure_ascii=False, sort_keys=True)
    logger.debug("%s %s", event, payload)


def _split_number(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    for pattern in (NUMERIC_RE, ROMAN_RE, ALPHA_RE):
        match = pattern.match(stripped)
        if match:
            number = match.group(0).rstrip(".-")
            remainder = stripped[match.end() :].lstrip(" )-.")
            return number, remainder or stripped[match.end() :].strip()
    return None, stripped


def _count_segments(number: str | None) -> int:
    if not number:
        return 0
    clean = number.rstrip(".-")
    if clean.isalpha() and len(clean) == 1:
        return 2
    segments = [segment for segment in clean.split(".") if segment]
    if not segments:
        return 1
    count = len(segments)
    if len(segments[0]) == 1 and segments[0].isalpha() and count > 1:
        count += 1
    return count


def _page_size_stats(lines: Sequence[TextLine]) -> dict[int, dict[str, float]]:
    stats: dict[int, dict[str, float]] = {}
    for line in lines:
        if line.font_size is None:
            continue
        bucket = stats.setdefault(line.page_no, {"sizes": [], "indents": []})
        bucket["sizes"].append(line.font_size)
        bucket["indents"].append(line.indent)
    results: dict[int, dict[str, float]] = {}
    for page, bucket in stats.items():
        sizes = bucket["sizes"] or [0.0]
        indents = bucket["indents"] or [0.0]
        median_size = statistics.median(sizes)
        stdev = statistics.pstdev(sizes) or 1.0
        indent_median = statistics.median(indents)
        results[page] = {
            "median_size": median_size,
            "stdev": stdev if stdev > 0 else 1.0,
            "indent_median": indent_median,
        }
    return results


def _is_probable_table(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("table ") or lowered.startswith("figure "):
        return True
    digits = sum(1 for char in text if char.isdigit())
    alpha = sum(1 for char in text if char.isalpha())
    return digits > alpha >= 1


def _score_candidate(line: TextLine, stats: dict[str, float], number: str | None) -> float:
    size = line.font_size or stats["median_size"]
    z = max(0.0, (size - stats["median_size"]) / max(stats["stdev"], 1.0))
    bold = 1.0 if line.is_bold else 0.0
    caps = 0.6 if line.is_caps else 0.0
    if number:
        depth = _count_segments(number)
        leading = 0.9 + 0.1 * max(depth - 1, 0)
    else:
        leading = 0.0
    indent_delta = stats["indent_median"] - line.indent
    indent_bonus = 0.0
    if indent_delta > 12:
        indent_bonus = 0.6
    elif indent_delta > 6:
        indent_bonus = 0.3
    elif indent_delta > 2:
        indent_bonus = 0.1
    elif number:
        if indent_delta < -12:
            indent_bonus = 0.2
        elif indent_delta < -6:
            indent_bonus = 0.1
    length_penalty = 0.0
    if len(line.text) > 120:
        length_penalty = 0.4
    elif len(line.text) > 80:
        length_penalty = 0.2
    score = 0.45 * z + 0.25 * bold + 0.15 * caps + 0.25 * leading + 0.15 * indent_bonus - length_penalty
    return max(score, 0.0)


def _detect_toc_pages(lines: Sequence[TextLine]) -> set[int]:
    scores: dict[int, int] = {}
    for line in lines:
        text = line.text.strip().lower()
        if not text:
            continue
        if DOT_LEADER_RE.search(text):
            scores[line.page_no] = scores.get(line.page_no, 0) + 2
        if any(keyword in text for keyword in TOC_KEYWORDS):
            scores[line.page_no] = scores.get(line.page_no, 0) + 4
    return {page for page, value in scores.items() if value >= 4}


def _detect_running_lines(lines: Sequence[TextLine], *, threshold: float = 0.6) -> set[tuple[int, str]]:
    if not lines:
        return set()
    total_pages = max(line.page_no for line in lines) + 1
    occurrences: dict[str, set[int]] = {}
    positions: dict[str, list[float]] = {}
    for line in lines:
        text = line.text.strip()
        if not text or len(text) > 80:
            continue
        if line.page_height:
            y_ratio = line.bbox[1] / max(line.page_height, 1.0)
            if 0.1 < y_ratio < 0.9:
                continue
        key = text.lower()
        occurrences.setdefault(key, set()).add(line.page_no)
        positions.setdefault(key, []).append(line.bbox[1])
    running: set[tuple[int, str]] = set()
    for key, pages in occurrences.items():
        if len(pages) / max(total_pages, 1) < threshold:
            continue
        avg_pos = sum(positions.get(key, [0.0])) / max(len(positions.get(key, [])), 1)
        running.add((round(avg_pos, 1), key))
    suppressed: set[tuple[int, str]] = set()
    for pos, key in running:
        suppressed.add((int(pos), key))
    return suppressed


def _running_match(line: TextLine, running: set[tuple[int, str]]) -> bool:
    if not running:
        return False
    text = line.text.strip().lower()
    if not text:
        return False
    avg_pos = int(round(line.bbox[1], 1))
    return (avg_pos, text) in running


def _infer_level(number: str | None, size: float | None, size_order: Sequence[float]) -> int:
    if number:
        return max(1, _count_segments(number))
    if not size_order:
        return 1
    if size is None:
        return len(size_order)
    for idx, threshold in enumerate(size_order, start=1):
        if size >= threshold:
            return idx
    return len(size_order)


def _size_order(lines: Sequence[_Candidate]) -> list[float]:
    sizes = sorted({round(candidate.line.font_size or 0.0, 1) for candidate in lines if candidate.line.font_size})
    sizes.sort(reverse=True)
    ordered: list[float] = []
    last = None
    for size in sizes:
        if last is None or abs(size - last) > 0.5:
            ordered.append(size)
            last = size
    return ordered


def _build_tree(candidates: Sequence[_Candidate], debug: bool) -> list[HeaderNode]:
    ordered_sizes = _size_order(candidates)
    root_stack: list[tuple[int, HeaderNode]] = []
    tree: list[HeaderNode] = []
    for candidate in candidates:
        level = candidate.level or _infer_level(candidate.number, candidate.line.font_size, ordered_sizes)
        level = max(1, min(level, 6))
        node = HeaderNode(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{candidate.line.page_no}:{candidate.line.line_idx}:{candidate.title}")),
            title=candidate.title,
            level=level,
            page=candidate.line.page_no,
            line_index=candidate.line.line_idx,
            number=candidate.number,
            score=candidate.score,
        )
        while root_stack and level <= root_stack[-1][0]:
            root_stack.pop()
        if root_stack:
            parent = root_stack[-1][1]
            parent.children.append(node)
        else:
            tree.append(node)
        root_stack.append((level, node))
        _structured_debug(
            debug,
            "headers.node",
            title=node.title,
            level=node.level,
            score=round(node.score, 3),
            page=node.page,
        )
    return tree


def _flatten_headers(tree: Sequence[HeaderNode]) -> list[HeaderItem]:
    items: list[HeaderItem] = []

    def visit(node: HeaderNode) -> None:
        number = node.number or ""
        header = HeaderItem(
            section_number=number,
            section_name=node.title,
            page_number=node.page + 1,
            line_number=node.line_index,
            chunk_text=node.title,
        )
        items.append(header)
        for child in node.children:
            visit(child)

    for root in tree:
        visit(root)
    return items


def detect_headers(
    lines: Iterable[TextLine],
    *,
    suppress_toc: bool = True,
    suppress_running: bool = True,
    debug: bool = False,
) -> HeaderDetectionResult:
    ordered_lines = sorted(lines, key=lambda line: (line.page_no, line.line_idx))
    page_stats = _page_size_stats(ordered_lines)
    toc_pages = _detect_toc_pages(ordered_lines) if suppress_toc else set()
    running_lines = _detect_running_lines(ordered_lines) if suppress_running else set()

    candidates: list[_Candidate] = []
    for line in ordered_lines:
        if suppress_toc and line.page_no in toc_pages:
            continue
        if suppress_running and _running_match(line, running_lines):
            continue
        if _is_probable_table(line.text):
            continue
        number, title = _split_number(line.text)
        stats = page_stats.get(line.page_no) or {"median_size": 0.0, "stdev": 1.0, "indent_median": line.indent}
        score = _score_candidate(line, stats, number)
        if score < 0.28:
            continue
        level = _count_segments(number) if number else 0
        candidate = _Candidate(line=line, score=score, number=number, title=title or line.text.strip(), level=level)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.line.page_no, item.line.line_idx))

    tree = _build_tree(candidates, debug)
    headers = _flatten_headers(tree)
    _structured_debug(
        debug,
        "headers.summary",
        total=len(headers),
        toc_pages=sorted(toc_pages),
    )
    return HeaderDetectionResult(headers=headers, tree=tree)
