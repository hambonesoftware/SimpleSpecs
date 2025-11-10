"""LLM-backed header extraction pipeline using full-document prompts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, TYPE_CHECKING

from backend.config import Settings

from ..utils.logging import configure_logging
from .openrouter_client import chat
from .token_chunk import split_by_token_limit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..utils.trace import HeaderTracer

FENCE_START = "-----BEGIN SIMPLEHEADERS JSON-----"
FENCE_END = "-----END SIMPLEHEADERS JSON-----"

# Safety wall for extremely large docs; actual token limit is min()'d with settings.
HEADER_CHUNK_TOKEN_LIMIT = 120_000

LOGGER = configure_logging().getChild(__name__)


@dataclass(slots=True)
class LLMFullHeadersResult:
    """Container for the full-LLM header extraction response."""

    headers: List[Dict]
    raw_responses: List[str]
    fenced_blocks: List[str]
    prompt_hash: str | None = None
    latency_ms: int | None = None
    from_cache: bool = False

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


class LLMFullHeadersParseError(RuntimeError):
    """Raised when the LLM returns an unparsable headers payload."""

    def __init__(self, message: str, *, content: str, part_index: int | None = None) -> None:
        super().__init__(message)
        self.content = content
        self.part_index = part_index


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
    """Return page-joined text blocks after filtering excluded/running content."""
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
    tracer: "HeaderTracer | None" = None,
    force: bool = False,  # NEW: bypass/purge cache and force fresh LLM call
) -> LLMFullHeadersResult:
    """Return LLM-extracted headers for a document.

    When `force=True`:
      - Skip reading the on-disk LLM cache entirely.
      - Best-effort purge any existing cache file for this `doc_hash`.
      - Always perform fresh OpenRouter calls and then overwrite cache.
    """

    if tracer is not None:
        tracer.log_call(f"{__name__}.get_headers_llm_full")

    # --------- Cache resolution (robust against None/str/Path) ----------
    cache_file: Path | None = None
    cache_dir_cfg = getattr(settings, "headers_llm_cache_dir", None)
    if cache_dir_cfg:
        cache_dir = Path(cache_dir_cfg)
        cache_file = _cache_path(cache_dir, doc_hash)

    # If forced, purge any existing cache file and bypass reads.
    if force and cache_file and cache_file.exists():
        try:
            cache_file.unlink()
            if tracer is not None:
                tracer.ev("llm_cache_purged", path=str(cache_file))
        except Exception:
            if tracer is not None:
                tracer.ev("llm_cache_purge_failed", path=str(cache_file))

    # If not forced, attempt cache read.
    if (not force) and cache_file and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            headers = cached.get("headers")
            if isinstance(headers, list):
                cleaned = [
                    {
                        "text": str(entry.get("text", "")),
                        "number": (entry.get("number") if entry.get("number") is not None else None),
                        "level": int(entry.get("level", 1) or 1),
                    }
                    for entry in headers
                    if isinstance(entry, dict)
                ]
                if tracer is not None:
                    tracer.ev("llm_cache_hit", path=str(cache_file))
                return LLMFullHeadersResult(
                    headers=cleaned,
                    raw_responses=[
                        str(entry)
                        for entry in cached.get("raw_responses", [])
                        if isinstance(entry, str)
                    ],
                    fenced_blocks=[
                        str(entry)
                        for entry in cached.get("fenced_blocks", [])
                        if isinstance(entry, str)
                    ],
                    from_cache=True,
                )
        except Exception:
            if tracer is not None:
                tracer.ev("llm_cache_read_failed", path=str(cache_file))

    if tracer is not None and cache_file:
        tracer.ev("llm_cache_miss", path=str(cache_file))

    # --------- Build LLM inputs ----------
    start_time = time.perf_counter()
    text_blocks = _build_text_blocks(lines, excluded_pages)
    token_limit = min(int(settings.headers_llm_max_input_tokens), HEADER_CHUNK_TOKEN_LIMIT)
    parts = split_by_token_limit(text_blocks, token_limit) or ["\n".join(text_blocks)]
    total_parts = len(parts)

    prompt_hasher = hashlib.sha256()

    client_params: dict[str, str] = {}
    if settings.openrouter_http_referer:
        client_params["http_referer"] = settings.openrouter_http_referer
    if settings.openrouter_title:
        client_params["x_title"] = settings.openrouter_title

    merged: list[Dict] = []
    raw_responses: list[str] = []
    fenced_blocks: list[str] = []

    # --------- Call OpenRouter part-by-part ----------
    for index, part in enumerate(parts, start=1):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a technical document-structure expert. Identify headings and "
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

        prompt_hasher.update(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )

        loop = asyncio.get_running_loop()
        if tracer is not None:
            tracer.ev(
                "llm_request",
                part=index,
                total_parts=total_parts,
                model=settings.headers_llm_model,
                temperature=0.2,
                params=dict(client_params),
                timeout_read=settings.headers_llm_timeout_s,
                messages=[dict(message) for message in messages],
            )

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
            (content or "").strip(),
        )
        raw_responses.append(content)

        try:
            data, fenced_block = _extract_fenced_json(content)
        except ValueError as exc:  # pragma: no cover - requires malformed provider output
            raise LLMFullHeadersParseError(
                str(exc) or "LLM response missing fenced SIMPLEHEADERS JSON",
                content=content,
                part_index=index,
            ) from exc

        fenced_blocks.append(fenced_block)
        headers_part = data.get("headers", [])
        if isinstance(headers_part, list):
            merged.extend(headers_part)

    # --------- Normalize & de-duplicate ----------
    deduped: list[Dict] = []
    seen: set[tuple[str, str]] = set()
    for header in merged:
        text = str(header.get("text", "")).strip()
        number_raw = header.get("number")
        number = str(number_raw).strip() if number_raw is not None else ""
        if not text:
            continue
        key = (text.lower(), number.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "text": text,
                "number": number or None,
                "level": int(header.get("level") or 1),
            }
        )

    # --------- Write cache (best-effort) ----------
    if cache_file is not None:
        try:
            cache_file.write_text(
                json.dumps(
                    {
                        "headers": deduped,
                        "raw_responses": raw_responses,
                        "fenced_blocks": fenced_blocks,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            if tracer is not None:
                tracer.ev("llm_cache_write", path=str(cache_file))
        except Exception:
            if tracer is not None:
                tracer.ev("llm_cache_write_failed", path=str(cache_file))

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    prompt_hash = prompt_hasher.hexdigest()

    return LLMFullHeadersResult(
        headers=deduped,
        raw_responses=raw_responses,
        fenced_blocks=fenced_blocks,
        prompt_hash=prompt_hash,
        latency_ms=latency_ms,
    )


__all__ = [
    "LLMFullHeadersResult",
    "get_headers_llm_full",
    "LLMFullHeadersParseError",
    "FENCE_START",
    "FENCE_END",
    "HEADER_CHUNK_TOKEN_LIMIT",
]
