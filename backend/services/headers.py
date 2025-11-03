"""Header extraction service backed exclusively by the LLM pipeline."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from ..config import Settings
from .openrouter_client import OpenRouterError, chat as openrouter_chat
from .pdf_native import ParsedPage, ParseResult

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
        return "LLM unavailable (429). Rate limit exceeded; retry later."
    if status == 500:
        return "LLM unavailable (500). OpenRouter server error."
    if isinstance(status, int):
        return f"LLM unavailable ({status})."
    return "LLM unavailable."


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
    """Extract a hierarchical header outline using the configured LLM."""

    fenced_empty = "\n".join(["#headers#", "#/headers#"])
    default_result = HeaderExtractionResult(
        outline=[],
        fenced_text=fenced_empty,
        source="openrouter",
    )

    if not llm_client or not llm_client.is_enabled:
        default_result.messages.append("LLM header extraction is disabled.")
        return default_result

    try:
        llm_result = llm_client.refine_outline(parse_result)
        if llm_result is not None:
            return llm_result
        default_result.messages.append("LLM did not return any headers.")
    except OpenRouterError as exc:  # pragma: no cover - network path
        LOGGER.warning("LLM extraction failed: %s", exc)
        default_result.messages.append(_format_openrouter_error(exc))
    except Exception as exc:  # pragma: no cover - other runtime issues
        LOGGER.warning("LLM extraction failed: %s", exc)
        default_result.messages.append("LLM header extraction failed.")

    return default_result


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


def build_outline_from_simpleheaders(
    entries: Sequence[Mapping[str, object]]
) -> list[HeaderNode]:
    """Convert a simple header list into ``HeaderNode`` hierarchy."""

    payload: list[dict[str, object]] = []
    for entry in entries:
        text = str(entry.get("text", "")).strip()
        if not text:
            continue

        number = entry.get("number")
        level = entry.get("level")
        try:
            level_int = int(level) if level is not None else 1
        except (TypeError, ValueError):
            level_int = 1
        page = entry.get("page")
        page_int = page if isinstance(page, int) else None

        payload.append(
            {
                "title": text,
                "number": number,
                "level": max(1, level_int),
                "page": page_int,
            }
        )

    return _build_outline_from_flat_entries(payload)


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
    """Client responsible for extracting outlines using the OpenRouter chat API."""

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
    ) -> HeaderExtractionResult | None:
        """Call OpenRouter and return the extracted headers."""

        if not self.is_enabled:
            return None

        prompt = _render_prompt(parse_result)
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
    parse_result: ParseResult,
) -> str:
    """Render the header extraction prompt using parse context only."""

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
        "- Ignore any previewed or summarised TOC items; use only headers from the main body context.\n"
        "- Do not omit appendices; include them as headers when present.\n"
        "- If no headers exist, return {\"headers\": []}.\n\n"
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
    "build_outline_from_simpleheaders",
]
