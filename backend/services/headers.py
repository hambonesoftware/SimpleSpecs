from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Sequence

import httpx

from ..constants import MAX_TOKENS_LIMIT

from ..config import Settings, get_settings
from ..logging import get_logger
from ..models import PARSED_OBJECT_ADAPTER, ParsedObject, SectionNode, SectionSpan
from ..text.toc_filters import (
    TOC_DOT_LEADER_LINE,
    is_probably_toc_line,
    mark_toc_pages,
)
from .llm_client import LLMAdapter

__all__ = ["build_headers_prompt", "parse_nested_list_to_tree"]

logger = get_logger(__name__)

_FALLBACK_NESTED_LIST = """1. Introduction\n  1.1 Background\n2. Methods\n3. Results"""
_MAX_PROMPT_CHARACTERS = 4000
_INDENT_WIDTH = 2
_BULLET_PREFIXES = ("- ", "* ", "+ ", "• ", "– ", "— ")
_ENUM_RE = re.compile(r"^(?:[0-9]+|[A-Za-z]+)(?:\.[0-9A-Za-z]+)*$")
_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")
_TOC_TRAILING_PAGE_RE = re.compile(
    r"([\._\u00B7\u2022\u22C5\u00B7\u2026\u2014\u2013\-]{2,}).{0,12}(\d{1,4}|[IVXLCDM]{1,7})\s*$",
    re.IGNORECASE,
)


@dataclass
class _LineItem:
    depth: int
    number: Optional[str]
    title: str


def _is_toc_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if TOC_DOT_LEADER_LINE.search(stripped):
        return True
    if _TOC_TRAILING_PAGE_RE.search(stripped):
        return True
    if is_probably_toc_line(stripped, in_toc_region=True):
        return True
    return False


def build_headers_prompt(objects: list[ParsedObject]) -> str:
    """Create a concise prompt asking the LLM to list document headers."""

    text_fragments: list[str] = []
    current_length = 0
    for obj in objects:
        if current_length >= _MAX_PROMPT_CHARACTERS:
            break
        content = (obj.text or "").strip()
        if not content:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            text_fragments.append(stripped)
            current_length += len(stripped) + 1
            if current_length >= _MAX_PROMPT_CHARACTERS:
                break

    excerpt = "\n".join(text_fragments)
    prompt = (
        "You are helping to outline a technical document. "
        "Review the provided excerpts and identify its headers.\n\n"
        f"Document excerpts:\n{excerpt}\n\n"
        "Please show a simple nested list of all headers and subheaders for this document."
    )
    return prompt


def parse_nested_list_to_tree(file_id: str, nested_list_text: str) -> SectionNode:
    """Convert a nested list description into a ``SectionNode`` tree."""

    items = _parse_list_text(nested_list_text)
    root = SectionNode(
        section_id=f"{file_id}-root",
        file_id=file_id,
        title="Document",
        depth=0,
    )

    counter = 1
    stack: list[tuple[int, SectionNode]] = [(-1, root)]
    for item in items:
        if not item.title:
            continue
        depth = max(item.depth, 0)
        parent_depth = stack[-1][0]
        if depth > parent_depth + 1:
            depth = parent_depth + 1
        while stack and depth <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        section = SectionNode(
            section_id=f"{file_id}-sec-{counter:04d}",
            file_id=file_id,
            number=item.number,
            title=item.title,
            depth=depth,
        )
        counter += 1
        parent.children.append(section)
        stack.append((depth, section))

    return root


def _parse_list_text(nested_list_text: str) -> list[_LineItem]:
    lines = [line.rstrip() for line in nested_list_text.splitlines()]
    items: list[_LineItem] = []
    last_depth = 0
    for raw_line in lines:
        line = raw_line.replace("\t", "    ")
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not stripped:
            continue
        number, title = _split_marker(stripped)
        if not title:
            continue
        depth = indent // _INDENT_WIDTH
        if depth > last_depth + 1:
            depth = last_depth + 1
        if depth < 0:
            depth = 0
        if number and "." in number:
            dotted = number.rstrip(".)")
            dot_count = dotted.count(".")
            if dot_count >= 1:
                depth = max(depth, dot_count)
        last_depth = depth
        items.append(_LineItem(depth=depth, number=number, title=title))
    return items


def _split_marker(text: str) -> tuple[Optional[str], str]:
    for prefix in _BULLET_PREFIXES:
        if text.startswith(prefix):
            return None, text[len(prefix) :].strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return None, text
    token, remainder = parts[0], parts[1]
    remainder = remainder.strip()
    candidate = _normalize_enumerator(token)
    if candidate is not None:
        return candidate, remainder
    return None, text


def _normalize_enumerator(token: str) -> Optional[str]:
    stripped = token.strip()
    if not stripped:
        return None
    paren = False
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
        paren = True
    suffix = ""
    if stripped.endswith(")"):
        stripped = stripped[:-1]
        suffix = ")"
    if stripped.endswith("."):
        stripped = stripped[:-1]
        suffix = "."
    if not stripped:
        return None
    upper = stripped.upper()
    if _ENUM_RE.match(stripped) or (_ROMAN_RE.match(upper) and len(upper) <= 4):
        if paren:
            return f"{stripped})"
        if suffix:
            return f"{stripped}{suffix}"
        return stripped
    if len(stripped) == 1 and stripped.isalpha():
        if paren:
            return f"{stripped})"
        return f"{stripped}."
    return None


def _normalize_text_for_match(text: str) -> str:
    cleaned = re.sub(r"[\s]+", " ", text)
    cleaned = re.sub(r"[^0-9A-Za-z ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _iter_sections(node: SectionNode) -> Iterator[SectionNode]:
    for child in node.children:
        yield child
        yield from _iter_sections(child)


def _prepare_object_lines(objects: Sequence[ParsedObject]) -> list[list[str]]:
    prepared: list[list[str]] = []
    page_lines: dict[int, list[str]] = {}

    for obj in objects:
        page_index = getattr(obj, "page_index", None)
        text = obj.text or ""
        if page_index is None or not text:
            continue
        for raw_line in text.splitlines():
            stripped_line = raw_line.strip()
            if stripped_line:
                page_lines.setdefault(page_index, []).append(stripped_line)

    toc_pages: set[int] = set()
    if page_lines:
        max_page = max(page_lines)
        pages = [page_lines.get(i, []) for i in range(max_page + 1)]
        toc_pages = mark_toc_pages(pages)

    for obj in objects:
        if getattr(obj, "page_index", None) in toc_pages:
            continue
        entries: list[str] = []
        seen: set[str] = set()
        text = obj.text or ""
        for line in text.splitlines():
            stripped_line = line.strip()
            if _is_toc_line(stripped_line):
                continue
            number, title = _split_marker(stripped_line)
            queue: list[tuple[Optional[str], str]] = [(number, title)]
            while queue:
                current_number, current_title = queue.pop(0)
                normalized_title = _normalize_text_for_match(current_title)
                if normalized_title and normalized_title not in seen:
                    entries.append(normalized_title)
                    seen.add(normalized_title)
                if current_number:
                    combined = f"{current_number} {current_title}".strip()
                    normalized_combined = _normalize_text_for_match(combined)
                    if normalized_combined and normalized_combined not in seen:
                        entries.append(normalized_combined)
                        seen.add(normalized_combined)
                sub_number, remainder = _split_marker(current_title)
                if remainder != current_title:
                    queue.append((sub_number, remainder))
        prepared.append(entries)
    return prepared


def _find_anchor(
    title: str, start_index: int, object_lines: list[list[str]]
) -> Optional[int]:
    target = _normalize_text_for_match(title)
    if not target:
        return None
    for idx in range(start_index, len(object_lines)):
        lines = object_lines[idx]
        for line in lines:
            if not line:
                continue
            if line == target or line.startswith(target) or target.startswith(line):
                return idx
    return None


def _assign_spans(
    root: SectionNode, objects: Sequence[ParsedObject]
) -> None:
    object_lines = _prepare_object_lines(objects)
    ordered_nodes = list(_iter_sections(root))
    start_map: dict[str, Optional[int]] = {}
    last_index = 0
    for node in ordered_nodes:
        anchor = _find_anchor(node.title, last_index, object_lines)
        if anchor is not None:
            start_map[node.section_id] = anchor
            last_index = anchor + 1
        else:
            start_map[node.section_id] = None

    def assign_recursive(node: SectionNode, boundary: int) -> None:
        children = node.children
        for idx, child in enumerate(children):
            next_boundary = boundary
            for sibling in children[idx + 1 :]:
                sibling_start = start_map.get(sibling.section_id)
                if sibling_start is not None:
                    next_boundary = sibling_start
                    break
            assign_recursive(child, next_boundary)
            start_idx = start_map.get(child.section_id)
            if start_idx is None:
                continue
            end_idx = next_boundary - 1
            if end_idx < start_idx:
                end_idx = start_idx
            end_idx = min(end_idx, len(objects) - 1)
            child.span = SectionSpan(
                start_object=objects[start_idx].object_id,
                end_object=objects[end_idx].object_id,
            )

    assign_recursive(root, len(objects))


def _persist_sections(file_id: str, root: SectionNode, settings: Settings) -> None:
    base = Path(settings.ARTIFACTS_DIR) / file_id / "headers"
    base.mkdir(parents=True, exist_ok=True)
    target = base / "sections.json"
    with target.open("w", encoding="utf-8") as handle:
        json.dump(root.model_dump(mode="json"), handle, indent=2)


class _FallbackAdapter:
    def generate(self, prompt: str) -> str:  # noqa: D401
        return _FALLBACK_NESTED_LIST


class _OpenRouterAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        api_key = self._settings.OPENROUTER_API_KEY
        if not api_key:
            return _FALLBACK_NESTED_LIST
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "openrouter/auto",
            "messages": [
                {"role": "system", "content": "Return only the nested list of headers."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS_LIMIT,
        }
        try:
            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Header LM raw response (OpenRouter adapter): %s", response.text)
            data = response.json()
            message = data.get("choices", [{}])[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
        except Exception:
            return _FALLBACK_NESTED_LIST
        return _FALLBACK_NESTED_LIST


class _LlamaCppAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        base_url = self._settings.LLAMACPP_URL
        if not base_url:
            return _FALLBACK_NESTED_LIST
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/completion",
                json={
                    "prompt": prompt,
                    "temperature": 0.0,
                    "max_tokens": MAX_TOKENS_LIMIT,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Header LM raw response (llama.cpp adapter): %s", response.text)
            data = response.json()
            content = data.get("content") or data.get("completion") or data.get("text")
            if isinstance(content, str) and content.strip():
                return content
        except Exception:
            return _FALLBACK_NESTED_LIST
        return _FALLBACK_NESTED_LIST


def _select_adapter(choice: str | None, settings: Settings) -> LLMAdapter:
    normalized = (choice or "openrouter").lower()
    if normalized == "openrouter":
        return _OpenRouterAdapter(settings)
    if normalized == "llamacpp":
        return _LlamaCppAdapter(settings)
    return _FallbackAdapter()


def run_header_discovery(file_id: str, llm_choice: str | None) -> SectionNode:
    settings = get_settings()
    objects_path = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    if not objects_path.exists():
        raise FileNotFoundError("parsed_objects_missing")
    with objects_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    objects = [PARSED_OBJECT_ADAPTER.validate_python(item) for item in data]
    prompt = build_headers_prompt(objects)
    adapter = _select_adapter(llm_choice, settings)
    try:
        response_text = adapter.generate(prompt)
    except Exception:
        response_text = _FALLBACK_NESTED_LIST
    logger.info("Header LM raw response (discovery): %s", response_text)
    if not isinstance(response_text, str) or not response_text.strip():
        response_text = _FALLBACK_NESTED_LIST
    root = parse_nested_list_to_tree(file_id, response_text)
    _assign_spans(root, objects)
    _persist_sections(file_id, root, settings)
    return root


def load_persisted_headers(file_id: str) -> SectionNode:
    settings = get_settings()
    sections_path = Path(settings.ARTIFACTS_DIR) / file_id / "headers" / "sections.json"
    if not sections_path.exists():
        raise FileNotFoundError("sections_missing")
    with sections_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return SectionNode.model_validate(payload)
