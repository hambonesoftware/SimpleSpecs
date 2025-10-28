"""Header extraction service combining heuristics with optional LLM refinement."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from ..config import Settings
from .openrouter_client import OpenRouterError, chat as openrouter_chat
from .pdf_native import ParsedBlock, ParsedPage, ParseResult

LOGGER = logging.getLogger(__name__)

NUMBERING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?P<number>\d+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+)$"),
    re.compile(r"^(?P<number>[A-Z](?:\.\d+)*)[.)]?\s+(?P<title>.+)$"),
    re.compile(
        r"^(?P<number>[IVXLCDM]+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+)$", re.IGNORECASE
    ),
)

APPENDIX_PATTERN = re.compile(
    r"^(?P<prefix>appendix|appendices)\s+(?P<identifier>[A-Z0-9]+(?:\.[A-Z0-9]+)*)\b(?P<rest>.*)$",
    re.IGNORECASE,
)


def _format_openrouter_error(exc: OpenRouterError) -> str:
    """Return a human-friendly description for OpenRouter failures."""

    status = getattr(exc, "status_code", None)
    if status == 401:
        return "LLM unavailable (401). Check OpenRouter API key configuration."
    if status == 403:
        return "LLM unavailable (403). Check API key / Referer headers."
    if status == 429:
        return "LLM unavailable (429). Rate limit exceeded; using heuristics."
    if status == 500:
        return "LLM unavailable (500). OpenRouter server error; using heuristics."
    if isinstance(status, int):
        return f"LLM unavailable ({status}). Using heuristic headers."
    return "LLM unavailable. Using heuristic headers."


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
    messages: list[str] = field(default_factory=list)

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
        except OpenRouterError as exc:  # pragma: no cover - network path
            LOGGER.warning("LLM refinement failed: %s", exc)
            heuristic_result.messages.append(_format_openrouter_error(exc))
        except Exception as exc:  # pragma: no cover - other runtime issues
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


def _score_block(
    block: ParsedBlock, avg_font_size: float, has_numbering: bool
) -> float:
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
    lowercase = text.lower()

    if lowercase.startswith("appendix"):
        score += 1.5

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
        node = HeaderNode(
            title=candidate.title, numbering=numbering, page=candidate.page_number
        )

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

    lines.append("#/headers#")
    return "\n".join(lines)


def flatten_outline(nodes: Sequence[HeaderNode]) -> list[dict[str, object]]:
    """Flatten a header outline into a list suitable for LLM alignment."""

    flattened: list[dict[str, object]] = []

    def _walk(node: HeaderNode, depth: int) -> None:
        flattened.append(
            {
                "text": node.title,
                "number": node.numbering or None,
                "level": max(1, depth),
            }
        )
        for child in node.children:
            _walk(child, depth + 1)

    for root in nodes:
        _walk(root, 1)

    return flattened


def _normalise_text(text: str) -> str:
    """Normalise whitespace within a block."""

    cleaned = " ".join(part.strip() for part in text.split())
    return cleaned.strip()


def _split_numbering(text: str) -> tuple[str | None, str]:
    """Split a heading into numbering and title components."""

    appendix_match = APPENDIX_PATTERN.match(text)
    if appendix_match:
        prefix = appendix_match.group("prefix") or "Appendix"
        identifier = appendix_match.group("identifier") or ""
        remainder = appendix_match.group("rest") or ""
        cleaned_remainder = remainder.lstrip(" .:-–—)\t")
        numbering = f"{prefix.upper()} {identifier.upper()}".strip()
        title = cleaned_remainder.strip()
        if not title:
            title = f"{prefix.title()} {identifier.upper()}".strip()
        return numbering, title

    for pattern in NUMBERING_PATTERNS:
        match = pattern.match(text)
        if match:
            number = match.group("number").upper()
            title = match.group("title").strip(" :")
            return number, title
    return None, text.strip(" :")


class HeadersLLMClient:
    """Client responsible for refining outlines using the OpenRouter chat API."""

    def __init__(
        self,
        settings: Settings,
        *,
        chat_func: Callable[..., str] | None = None,
    ) -> None:
        self._settings = settings
        self._chat = chat_func or openrouter_chat

    @property
    def is_enabled(self) -> bool:
        """Return True when LLM refinement should be attempted."""

        return bool(self._settings.openrouter_api_key)

    def refine_outline(
        self,
        parse_result: ParseResult,
        heuristic_result: HeaderExtractionResult,
    ) -> HeaderExtractionResult | None:
        """Call OpenRouter and merge the returned headers with heuristics."""

        if not self.is_enabled:
            return None

        prompt = _render_prompt(parse_result, heuristic_result)
        messages = [{"role": "user", "content": prompt}]

        headers: dict[str, str] = {}
        if self._settings.openrouter_http_referer:
            referer = self._settings.openrouter_http_referer.strip()
            if referer:
                headers["HTTP-Referer"] = referer
                headers["Referer"] = referer
        if self._settings.openrouter_title:
            title = self._settings.openrouter_title.strip()
            if title:
                headers["X-Title"] = title

        try:
            response_text = self._chat(
                messages,
                model=self._settings.headers_llm_model,
                temperature=0.2,
                params={},
                headers=headers,
                timeout_read=self._settings.headers_llm_timeout_s,
            )
        except OpenRouterError:
            raise
        except Exception as exc:  # pragma: no cover - runtime issues
            LOGGER.warning("LLM refinement failed: %s", exc)
            return None

        payload = _parse_llm_headers(response_text)
        if payload is None:
            return None

        outline = _build_outline_from_payload(payload.get("headers", []))
        if not outline:
            return None

        serialised = json.dumps(payload, ensure_ascii=False, indent=2)
        fenced_text = "\n".join(["#headers#", serialised, "#/headers#"])
        return HeaderExtractionResult(
            outline=outline,
            fenced_text=fenced_text,
            source="openrouter",
        )


def _render_prompt(
    parse_result: ParseResult, heuristic_result: HeaderExtractionResult
) -> str:
    """Render the header extraction prompt with heuristic hints."""

    heuristic_lines = [
        line
        for line in heuristic_result.fenced_text.splitlines()
        if line not in {"#headers#", "#/headers#"}
    ]
    heuristic_block = "\n".join(heuristic_lines) or "<no heuristic headers>"

    def _sample_page(page: ParsedPage, *, limit: int = 15) -> list[str]:
        lines: list[str] = []
        for block in page.blocks:
            normalised = _normalise_text(block.text)
            if normalised:
                lines.append(normalised)
            if len(lines) >= limit:
                break
        return lines

    page_summaries: list[str] = []
    included_pages: set[int] = set()
    for page in parse_result.pages[:3]:
        sample_lines = _sample_page(page)
        if sample_lines:
            page_summaries.append(
                f"Page {page.page_number}:\n" + "\n".join(sample_lines)
            )
            included_pages.add(page.page_number)

    appendix_summaries: list[str] = []
    for page in parse_result.pages:
        if len(appendix_summaries) >= 2:
            break
        if page.page_number in included_pages:
            continue
        sample_lines = _sample_page(page)
        if not sample_lines:
            continue
        if not any("appendix" in line.lower() for line in sample_lines):
            continue
        appendix_summaries.append(
            f"Appendix preview (Page {page.page_number}):\n" + "\n".join(sample_lines)
        )
        included_pages.add(page.page_number)

    context_sections: list[str] = []
    if page_summaries:
        context_sections.append("\n\n".join(page_summaries))
    if appendix_summaries:
        context_sections.append("\n\n".join(appendix_summaries))

    context_block = (
        "\n\n".join(context_sections) if context_sections else "(No preview text available)"
    )

    prompt = (
        "Return ONLY this fence:\n\n"
        "#headers#\n"
        "{\"headers\": [{\"title\": \"...\", \"number\": \"...\" | null, \"level\": 1}]}\n"
        "#/headers#\n\n"
        "Rules:\n"
        "- No prose before or after the fence.\n"
        "- Every header must include \"title\" and integer \"level\" (1 = top level).\n"
        "- Include \"number\" when the source shows one; otherwise use null.\n"
        "- Preserve document order and exclude tables of contents or running headers.\n"
        "- Do not omit appendices; include them as headers when present.\n"
        "- If no headers exist, return {\"headers\": []}.\n\n"
        "Heuristic outline (may be incomplete):\n"
        f"{heuristic_block}\n\n"
        "Context:\n"
        f"{context_block}"
    )
    return prompt


def _parse_llm_headers(content: str) -> dict[str, Any] | None:
    """Extract JSON payload from the LLM response with fallback sniffing."""

    start_token = "#headers#"
    end_token = "#/headers#"
    start = content.find(start_token)
    end = content.rfind(end_token)
    if start != -1 and end != -1 and end > start:
        candidate = content[start + len(start_token) : end].strip()
    else:
        LOGGER.warning("LLM response missing #headers# fence")
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            return None
        candidate = match.group(0)

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        LOGGER.warning("LLM headers response was not valid JSON")
        return None

    if isinstance(data, list):
        data = {"headers": data}

    if not isinstance(data, dict):
        return None

    headers_payload = data.get("headers") or []
    if not isinstance(headers_payload, list):
        return None

    normalised: list[dict[str, Any]] = []
    for entry in headers_payload:
        normalised_entry = _normalise_header_entry(entry)
        if normalised_entry:
            normalised.append(normalised_entry)

    return {"headers": normalised}


def _normalise_header_entry(entry: Any) -> dict[str, Any] | None:
    """Return a normalised header mapping or ``None`` if invalid."""

    if not isinstance(entry, Mapping):
        return None

    title = str(entry.get("title") or entry.get("text") or "").strip()
    if not title:
        return None

    number = entry.get("number") or entry.get("label") or entry.get("heading_number")
    if number is not None:
        number = str(number).strip()
        if not number:
            number = None

    raw_level = entry.get("level")
    try:
        level = int(raw_level)
    except (TypeError, ValueError):
        level = 1
    level = max(1, level)

    page = entry.get("page")
    if not isinstance(page, int):
        page = None

    children_entries = entry.get("children") if isinstance(entry, Mapping) else None
    children: list[dict[str, Any]] = []
    if isinstance(children_entries, list):
        for child in children_entries:
            normalised_child = _normalise_header_entry(child)
            if normalised_child:
                children.append(normalised_child)

    result: dict[str, Any] = {
        "title": title,
        "number": number,
        "level": level,
    }
    if page is not None:
        result["page"] = page
    if children:
        result["children"] = children

    return result


def _build_outline_from_payload(entries: Sequence[Mapping[str, Any]]) -> list[HeaderNode]:
    """Convert normalised header entries into ``HeaderNode`` objects."""

    if any(entry.get("children") for entry in entries):
        return [_build_outline_recursive(entry) for entry in entries]

    return _build_outline_from_flat_entries(entries)


def _build_outline_recursive(entry: Mapping[str, Any]) -> HeaderNode:
    title = str(entry.get("title", ""))
    number = str(entry.get("number") or "")
    page = entry.get("page") if isinstance(entry.get("page"), int) else None
    node = HeaderNode(title=title, numbering=number, page=page)
    children = entry.get("children")
    if isinstance(children, list):
        for child in children:
            normalised = _normalise_header_entry(child)
            if normalised:
                node.children.append(_build_outline_recursive(normalised))
    return node


def _build_outline_from_flat_entries(
    entries: Sequence[Mapping[str, Any]]
) -> list[HeaderNode]:
    nodes: list[HeaderNode] = []
    stack: list[tuple[int, HeaderNode]] = []

    for entry in entries:
        title = str(entry.get("title", ""))
        if not title:
            continue
        number = str(entry.get("number") or "")
        level = int(entry.get("level") or 1)
        page = entry.get("page") if isinstance(entry.get("page"), int) else None
        node = HeaderNode(title=title, numbering=number, page=page)

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
    "flatten_outline",
]
