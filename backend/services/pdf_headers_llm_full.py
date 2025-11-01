"""LLM-backed header extraction pipeline using full-document prompts."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from backend.config import Settings

from .openrouter_client import chat
from .token_chunk import split_by_token_limit

FENCE_START = "-----BEGIN SIMPLEHEADERS JSON-----"
FENCE_END = "-----END SIMPLEHEADERS JSON-----"

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "headers_with_locations.txt"
try:
    PROMPT_WITH_LOCATIONS = PROMPT_PATH.read_text(encoding="utf-8").strip()
except FileNotFoundError:  # pragma: no cover - optional runtime asset
    PROMPT_WITH_LOCATIONS = ""


def _cache_path(cache_dir: Path, doc_hash: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{doc_hash}.simpleheaders.json"


def _extract_fenced_json(content: str) -> Dict:
    match = re.search(
        re.escape(FENCE_START) + r"(.*?)" + re.escape(FENCE_END), content, re.S
    )
    if not match:
        raise ValueError("LLM response missing fenced SIMPLEHEADERS JSON")
    payload = match.group(1)
    return json.loads(payload)


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _extract_json_block(content: str) -> Dict:
    match = JSON_BLOCK_RE.search(content)
    if not match:
        raise ValueError("LLM response missing JSON block")
    return json.loads(match.group(1))


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalise_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    text = str(entry.get("text") or entry.get("title") or "").strip()
    if not text:
        return None

    number_raw = entry.get("number") or entry.get("uid")
    number = str(number_raw).strip() if number_raw is not None else None
    if number:
        number = number or None

    try:
        level = int(entry.get("level") or 1)
    except (TypeError, ValueError):
        level = 1

    page_hint = _coerce_int(
        entry.get("page_hint") or entry.get("page_estimate") or entry.get("page")
    )
    line_hint = _coerce_int(
        entry.get("line_hint") or entry.get("line_estimate") or entry.get("line")
    )

    return {
        "text": text,
        "number": number or None,
        "level": level,
        "page_hint": page_hint,
        "line_hint": line_hint,
        "children": entry.get("children"),
    }


def _collect_entries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def _append(entry: Mapping[str, Any]) -> None:
        normalised = _normalise_entry(entry)
        if not normalised:
            return
        children = normalised.pop("children", None)
        entries.append(normalised)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, Mapping):
                    _append(child)

    raw_headers = payload.get("headers")
    if isinstance(raw_headers, list):
        for entry in raw_headers:
            if isinstance(entry, Mapping):
                _append(entry)

    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, list):
        for entry in raw_nodes:
            if isinstance(entry, Mapping):
                _append(entry)

    return entries


def _build_text_blocks(
    lines: Sequence[Dict], excluded_pages: Iterable[int]
) -> List[str]:
    excluded = set(int(page) for page in excluded_pages)
    filtered = [
        line
        for line in lines
        if line.get("page") not in excluded and not line.get("is_running")
    ]
    if not filtered:
        return [""]

    blocks: list[str] = []
    current_page = filtered[0].get("page")
    buffer: list[str] = []

    for line in filtered:
        page = line.get("page")
        if page != current_page:
            blocks.append("\n".join(buffer))
            buffer = []
            current_page = page
        buffer.append(str(line.get("text", "")))

    if buffer:
        blocks.append("\n".join(buffer))

    return blocks


async def get_headers_llm_full(
    lines: Sequence[Dict],
    doc_hash: str,
    *,
    settings: Settings,
    excluded_pages: Iterable[int] = (),
) -> List[Dict]:
    """Return LLM extracted headers for a document."""

    cache_file = _cache_path(settings.headers_llm_cache_dir, doc_hash)
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        headers = cached.get("headers")
        if isinstance(headers, list):
            return headers  # type: ignore[return-value]

    text_blocks = _build_text_blocks(lines, excluded_pages)
    parts = split_by_token_limit(
        text_blocks, settings.headers_llm_max_input_tokens
    )
    if not parts:
        parts = ["\n".join(text_blocks)]

    client_params: dict[str, str] = {}
    if settings.openrouter_http_referer:
        client_params["http_referer"] = settings.openrouter_http_referer
    if settings.openrouter_title:
        client_params["x_title"] = settings.openrouter_title

    merged: list[Dict] = []
    total_parts = len(parts)

    for index, part in enumerate(parts, start=1):
        if settings.headers_llm_include_locations and PROMPT_WITH_LOCATIONS:
            user_prompt = (
                f"{PROMPT_WITH_LOCATIONS}\n\n"
                f"Document part {index}/{total_parts}:\n<BEGIN DOCUMENT>\n{part}\n<END DOCUMENT>\n"
            )
        else:
            user_prompt = (
                "Goal: Return every heading and subheading that appears in the MAIN BODY of the document.\n"
                "Hard rules:\n"
                "- EXCLUDE any content in a Table of Contents, Index, or Glossary.\n"
                "- Preserve the original document order.\n"
                "- If a heading has a visible numbering label (e.g., \"1\", \"1.2\", \"A.3.4\"), include it as \"number\"; otherwise set \"number\": null.\n"
                "- Assign a positive integer \"level\" (1 = top-level).\n"
                "- Do NOT invent headings; only list those present.\n"
                "- Output EXACTLY the fenced JSON:\n\n"
                f"{FENCE_START}\n"
                "{ \"headers\": [ { \"text\": \"...\", \"number\": \"...\" | null, \"level\": 1 }, ... ] }\n"
                f"{FENCE_END}\n\n"
                f"Document part {index}/{total_parts}:\n<BEGIN DOCUMENT>\n{part}\n<END DOCUMENT>\n"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a technical document structure expert. Identify headings and "
                    "their nesting levels from the full document text."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            None,
            lambda: chat(
                [dict(message) for message in messages],
                model=settings.headers_llm_model,
                temperature=0.2,
                params=client_params,
                timeout_read=settings.headers_llm_timeout_s,
            ),
        )
        if settings.headers_llm_include_locations:
            try:
                data = _extract_fenced_json(content)
            except ValueError:
                data = _extract_json_block(content)
        else:
            data = _extract_fenced_json(content)
        merged.extend(_collect_entries(data))

    deduped: list[Dict] = []
    seen: set[tuple[str, str]] = set()
    for header in merged:
        text = str(header.get("text", "")).strip()
        number = (header.get("number") or "").strip()
        key = (text.lower(), number.lower())
        if key in seen or not text:
            continue
        seen.add(key)
        entry: dict[str, Any] = {
            "text": text,
            "number": number or None,
            "level": int(header.get("level") or 1),
            "page_hint": _coerce_int(header.get("page_hint")),
            "line_hint": _coerce_int(header.get("line_hint")),
        }
        deduped.append(entry)

    base = settings.headers_llm_page_index_base
    adjusted: list[Dict] = []
    for entry in deduped:
        page_hint = _coerce_int(entry.get("page_hint"))
        if page_hint is not None:
            entry["page_hint"] = max(0, page_hint - base)
        else:
            entry["page_hint"] = None
        line_hint = _coerce_int(entry.get("line_hint"))
        entry["line_hint"] = line_hint
        adjusted.append(entry)

    cache_file.write_text(
        json.dumps({"headers": adjusted}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return adjusted


__all__ = ["get_headers_llm_full", "FENCE_START", "FENCE_END"]
