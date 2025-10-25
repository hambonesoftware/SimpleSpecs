"""Header extraction service combining heuristics with optional LLM refinement."""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from ..config import Settings
from .llm import LLMProviderError, LLMCircuitOpenError, LLMService
from .pdf_native import ParsedBlock, ParseResult

LOGGER = logging.getLogger(__name__)

NUMBERING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?P<number>\d+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+)$"),
    re.compile(r"^(?P<number>[A-Z](?:\.\d+)*)[.)]?\s+(?P<title>.+)$"),
    re.compile(r"^(?P<number>[IVXLCDM]+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+)$", re.IGNORECASE),
)


@dataclass(slots=True)
class HeaderCandidate:
    """Potential header extracted from PDF text blocks."""

    title: str
    numbering: str | None
    page_number: int
    level_hint: int
    indent: float
    top: float
    score: float


@dataclass(slots=True)
class HeaderNode:
    """Hierarchical header node returned to clients."""

    title: str
    numbering: str
    page: int | None
    children: list["HeaderNode"] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a serialisable representation of the node."""

        return {
            "title": self.title,
            "numbering": self.numbering,
            "page": self.page,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(slots=True)
class HeaderExtractionResult:
    """Container describing the final outline and metadata."""

    outline: list[HeaderNode]
    fenced_text: str
    source: str

    def to_json(self) -> list[dict]:
        """Return outline as JSON-compatible list."""

        return [node.to_dict() for node in self.outline]


def extract_headers(
    parse_result: ParseResult,
    *,
    settings: Settings,
    llm_client: "HeadersLLMClient | None" = None,
) -> HeaderExtractionResult:
    """Extract a hierarchical header outline from a parse result."""

    candidates = _collect_candidates(parse_result)
    outline = _build_outline(candidates)
    heuristic_result = HeaderExtractionResult(
        outline=outline,
        fenced_text=_outline_to_fenced_text(outline),
        source="heuristic",
    )

    if llm_client and llm_client.is_enabled:
        try:
            llm_result = llm_client.refine_outline(parse_result, heuristic_result)
            if llm_result is not None:
                return llm_result
        except Exception as exc:  # pragma: no cover - network exceptions
            LOGGER.warning("LLM refinement failed: %s", exc)

    return heuristic_result


def _collect_candidates(parse_result: ParseResult) -> list[HeaderCandidate]:
    """Return sorted header candidates based on heuristics."""

    font_sizes: list[float] = []
    for page in parse_result.pages:
        for block in page.blocks:
            if block.font_size:
                font_sizes.append(block.font_size)

    avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0

    candidates: list[HeaderCandidate] = []
    for page in parse_result.pages:
        if page.is_toc:
            continue
        for block in page.blocks:
            text = _normalise_text(block.text)
            if not text:
                continue

            numbering, title = _split_numbering(text)
            score = _score_block(block, avg_font_size, bool(numbering))
            if not numbering and score < 1.5:
                continue

            level_hint = _infer_level(numbering, block)
            candidate = HeaderCandidate(
                title=title,
                numbering=numbering,
                page_number=page.page_number,
                level_hint=level_hint,
                indent=block.bbox[0],
                top=block.bbox[1],
                score=score,
            )
            candidates.append(candidate)

    candidates.sort(key=lambda c: (c.page_number, c.top))
    return candidates


def _score_block(block: ParsedBlock, avg_font_size: float, has_numbering: bool) -> float:
    """Calculate a heuristic score for a block."""

    score = 0.0
    if has_numbering:
        score += 2.5

    if block.font_size and avg_font_size:
        diff = block.font_size - avg_font_size
        if diff > 1.0:
            score += 1.5
        elif diff > 0.5:
            score += 0.5

    text = _normalise_text(block.text)
    if text.isupper() and len(text.split()) <= 6:
        score += 1.0
    elif text.istitle():
        score += 0.5

    return score


def _infer_level(numbering: str | None, block: ParsedBlock) -> int:
    """Determine the likely nesting level for a candidate."""

    if numbering:
        segments = re.split(r"[.]+", numbering.strip(".) "))
        segments = [seg for seg in segments if seg]
        if segments:
            return len(segments)

    indent = block.bbox[0]
    if indent <= 10:
        return 1
    return min(1 + int(math.floor(indent / 40.0)), 6)


def _build_outline(candidates: Sequence[HeaderCandidate]) -> list[HeaderNode]:
    """Build a tree from the candidate list."""

    if not candidates:
        return []

    indent_buckets = _cluster_indents(candidates)
    outline: list[HeaderNode] = []
    stack: list[tuple[int, HeaderNode]] = []
    counters: dict[int, int] = defaultdict(int)

    for candidate in candidates:
        level = _resolve_level(candidate, indent_buckets)
        if candidate.numbering:
            _sync_counters(candidate.numbering, counters)
            numbering = candidate.numbering
        else:
            numbering = _auto_number(level, counters)
        node = HeaderNode(title=candidate.title, numbering=numbering, page=candidate.page_number)

        while stack and stack[-1][0] >= level:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            outline.append(node)

        stack.append((level, node))

    return outline


def _cluster_indents(candidates: Sequence[HeaderCandidate]) -> list[float]:
    """Group indent values into discrete buckets to stabilise level inference."""

    values = sorted({round(candidate.indent, 2) for candidate in candidates})
    if not values:
        return [0.0]

    buckets = [values[0]]
    for value in values[1:]:
        if abs(value - buckets[-1]) > 12.0:
            buckets.append(value)
    return buckets


def _resolve_level(candidate: HeaderCandidate, indent_buckets: Sequence[float]) -> int:
    """Resolve a final level using indentation and hints."""

    level = candidate.level_hint
    indent = candidate.indent
    for index, bucket in enumerate(indent_buckets, start=1):
        if indent <= bucket + 1e-3:
            level = min(level, index)
            break
    return max(1, level)


def _auto_number(level: int, counters: dict[int, int]) -> str:
    """Assign synthetic numbering for unnumbered headers."""

    counters[level] = counters.get(level, 0) + 1
    for deeper_level in list(counters.keys()):
        if deeper_level > level:
            counters[deeper_level] = 0

    parts: list[str] = []
    for depth in range(1, level + 1):
        value = counters.get(depth)
        if not value:
            value = 1
            counters[depth] = value
        parts.append(str(value))
    return ".".join(parts)


def _sync_counters(numbering: str, counters: dict[int, int]) -> None:
    """Align numeric counters with explicit numbering from the document."""

    try:
        parts = [int(part) for part in numbering.split(".")]
    except ValueError:
        return

    for index, value in enumerate(parts, start=1):
        counters[index] = value

    for deeper_level in list(counters.keys()):
        if deeper_level > len(parts):
            counters[deeper_level] = 0


def _outline_to_fenced_text(nodes: Sequence[HeaderNode]) -> str:
    """Render the outline as fenced text."""

    lines = ["#headers#"]

    def _emit(node: HeaderNode, depth: int) -> None:
        indent = "  " * depth
        label = f"{node.numbering} {node.title}".strip()
        lines.append(f"{indent}{label}")
        for child in node.children:
            _emit(child, depth + 1)

    for node in nodes:
        _emit(node, 0)

    lines.append("#headers#")
    return "\n".join(lines)


def _normalise_text(text: str) -> str:
    """Normalise whitespace within a block."""

    cleaned = " ".join(part.strip() for part in text.split())
    return cleaned.strip()


def _split_numbering(text: str) -> tuple[str | None, str]:
    """Split a heading into numbering and title components."""

    for pattern in NUMBERING_PATTERNS:
        match = pattern.match(text)
        if match:
            number = match.group("number").upper()
            title = match.group("title").strip(" :")
            return number, title
    return None, text.strip(" :")


class HeadersLLMClient:
    """Client responsible for refining outlines using the shared LLM service."""

    def __init__(self, settings: Settings, llm_service: LLMService | None = None) -> None:
        self._settings = settings
        self._llm = llm_service or LLMService(settings)

    @property
    def is_enabled(self) -> bool:
        """Return True when LLM refinement should be attempted."""

        return self._llm.is_enabled

    def refine_outline(
        self,
        parse_result: ParseResult,
        heuristic_result: HeaderExtractionResult,
    ) -> HeaderExtractionResult | None:
        """Call the LLM service and validate fenced outline output."""

        if not self.is_enabled:
            return None

        messages = self._build_messages(parse_result, heuristic_result)
        try:
            result = self._llm.generate(
                messages=messages,
                fence="#headers#",
                metadata={"task": "headers"},
            )
        except (LLMCircuitOpenError, LLMProviderError) as exc:  # pragma: no cover - network path
            LOGGER.warning("LLM refinement failed: %s", exc)
            return None

        fenced_text = result.fenced or result.content
        lines = _parse_llm_headers(fenced_text)
        if not lines:
            return None

        outline = _build_outline_from_lines(lines)
        cleaned_fenced = "\n".join(["#headers#", *lines, "#headers#"])
        return HeaderExtractionResult(outline=outline, fenced_text=cleaned_fenced, source=self._llm.get_provider())

    def _build_messages(
        self,
        parse_result: ParseResult,
        heuristic_result: HeaderExtractionResult,
    ) -> list[dict[str, str]]:
        prompt_body = _render_prompt(parse_result, heuristic_result)
        return [
            {
                "role": "system",
                "content": (
                    "You are a document structure extractor. Return a complete numbered outline "
                    "enclosed in #headers# fences."
                ),
            },
            {"role": "user", "content": prompt_body},
        ]


def _render_prompt(parse_result: ParseResult, heuristic_result: HeaderExtractionResult) -> str:
    """Render the header extraction prompt with heuristic hints."""

    sample_lines = [line for line in heuristic_result.fenced_text.splitlines() if line not in {"#headers#"}]
    sample = "\n".join(sample_lines)
    pages_summary = []
    for page in parse_result.pages[:3]:
        page_lines = [
            _normalise_text(block.text)
            for block in page.blocks[:15]
            if _normalise_text(block.text)
        ]
        pages_summary.append(f"Page {page.page_number}:\n" + "\n".join(page_lines))

    context = "\n\n".join(pages_summary)
    prompt = (
        "You are a document structure extractor.\n"
        "Goal: produce a complete numbered nested list of all headers/subheaders.\n\n"
        "Return ONLY the list enclosed in #headers# fences, e.g.:\n\n"
        "#headers#\n1. Top Level\n   1.1 Sub\n      1.1.1 Sub-sub\n2. Another Top\n#headers#\n\n"
        "Rules:\n"
        "- Include annexes/appendices where relevant.\n"
        "- Ignore page headers/footers and running titles.\n"
        "- DO NOT include table-of-contents sections.\n"
        "- Preserve document-native numbering if present (1, 1.1, I, A, A.1, etc.).\n"
        "- If unnumbered, infer stable outline numbering.\n\n"
        "Context extracted from PDF pages:\n"
        f"{context}\n\n"
        "Heuristic outline (may be incomplete):\n"
        f"{sample}"
    )
    return prompt


def _parse_llm_headers(content: str) -> list[str]:
    """Validate that the LLM response obeys the #headers# fence."""

    match = re.search(r"#headers#(.*?)#headers#", content, re.DOTALL)
    if not match:
        LOGGER.warning("LLM response missing #headers# fence")
        return []

    body = match.group(1).strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return lines


def _build_outline_from_lines(lines: Sequence[str]) -> list[HeaderNode]:
    """Construct outline nodes from fenced text lines."""

    nodes: list[HeaderNode] = []
    stack: list[tuple[int, HeaderNode]] = []

    for raw_line in lines:
        number, title = _split_numbering(raw_line)
        if not number:
            continue
        level = len(number.split("."))
        node = HeaderNode(title=title, numbering=number, page=None)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            nodes.append(node)
        stack.append((level, node))

    return nodes


__all__ = [
    "HeaderExtractionResult",
    "HeaderNode",
    "HeadersLLMClient",
    "extract_headers",
]

