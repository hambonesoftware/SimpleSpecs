"""LLM-backed header extraction pipeline using full-document prompts."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from backend.config import Settings

from ..utils.logging import configure_logging
from .openrouter_client import chat
from .token_chunk import split_by_token_limit

FENCE_START = "-----BEGIN SIMPLEHEADERS JSON-----"
FENCE_END = "-----END SIMPLEHEADERS JSON-----"


LOGGER = configure_logging().getChild(__name__)


@dataclass(slots=True)
class LLMFullHeadersResult:
    """Container for the full-LLM header extraction response."""

    headers: List[Dict]
    raw_responses: List[str]
    fenced_blocks: List[str]

    def combined_fenced(self) -> str:
        """Return a single fenced block for downstream consumers."""

        if self.fenced_blocks:
            cleaned = [block.strip("\n") for block in self.fenced_blocks if block.strip()]
            if cleaned:
                return "\n\n".join(cleaned)
        payload = json.dumps({"headers": self.headers}, ensure_ascii=False, indent=2)
        return "\n".join([FENCE_START, payload, FENCE_END])


def _cache_path(cache_dir: Path, doc_hash: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{doc_hash}.simpleheaders.json"


def _extract_fenced_json(content: str) -> tuple[Dict, str]:
    match = re.search(
        re.escape(FENCE_START) + r"(.*?)" + re.escape(FENCE_END), content, re.S
    )
    if not match:
        raise ValueError("LLM response missing fenced SIMPLEHEADERS JSON")
    payload = match.group(1)
    fenced_block = match.group(0)
    return json.loads(payload), fenced_block


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
    raw_responses: list[str] = []
    fenced_blocks: list[str] = []
    total_parts = len(parts)

    for index, part in enumerate(parts, start=1):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a technical document structure expert. Identify headings and "
                    "their nesting levels from the full document text."
                ),
            },
            {
                "role": "user",
                "content": (
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
                ),
            },
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
        LOGGER.info(
            "[headers.llm_full] Raw LLM response part %s/%s:\n%s",
            index,
            total_parts,
            content.strip(),
        )
        raw_responses.append(content)
        data, fenced_block = _extract_fenced_json(content)
        fenced_blocks.append(fenced_block)
        merged.extend(data.get("headers", []))

    deduped: list[Dict] = []
    seen: set[tuple[str, str]] = set()
    for header in merged:
        text = str(header.get("text", "")).strip()
        number = (header.get("number") or "").strip()
        key = (text.lower(), number.lower())
        if key in seen or not text:
            continue
        seen.add(key)
        deduped.append(
            {
                "text": text,
                "number": number or None,
                "level": int(header.get("level") or 1),
            }
        )

    cache_file.write_text(
        json.dumps({"headers": deduped}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return LLMFullHeadersResult(
        headers=deduped,
        raw_responses=raw_responses,
        fenced_blocks=fenced_blocks,
    )


__all__ = [
    "LLMFullHeadersResult",
    "get_headers_llm_full",
    "FENCE_START",
    "FENCE_END",
]
