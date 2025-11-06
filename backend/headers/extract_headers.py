"""Retry-aware header extraction orchestration."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from backend.services.openrouter_client import OpenRouterError

from .chunk import ChunkPage, make_chunks, stitch_chunks
from .legacy_locator import legacy_outline
from .llm_client import LLMClient
from .models import AttemptSummary, ExtractHeadersResult, HeaderItem
from .normalize import normalize_headers
from .prompt import build_prompt
from .validators import (
    detect_bad_label,
    extract_fenced_simpleheaders_block,
    parse_fenced_payload,
)

try:  # pragma: no cover - avoid circular import failures during packaging
    from backend.config import get_settings
except Exception:  # pragma: no cover - fallback during docs builds
    get_settings = None  # type: ignore[assignment]


@dataclass(slots=True)
class HeadersConfig:
    """Configuration driving the extractor ladder."""

    model: str
    fallback_model: str
    timeout_s: int
    max_input_tokens: int
    cache_dir: Path
    chunking: str = "auto"
    chunk_target_tokens: int = 35_000
    retry_max: int = 3
    backoff_s: float = 2.0
    suppress_toc: bool = True
    suppress_running: bool = True
    normalize_confusables: bool = True
    strict_invariants: bool = True
    title_only_reanchor: bool = True

    @classmethod
    def from_env(cls) -> "HeadersConfig":
        if get_settings is None:
            raise RuntimeError("Settings loader unavailable")
        settings = get_settings()
        return cls.from_settings(settings)

    @classmethod
    def from_settings(cls, settings) -> "HeadersConfig":
        chunking = getattr(settings, "headers_llm_chunking", "auto")
        fallback_model = getattr(
            settings,
            "headers_llm_model_fallback",
            getattr(settings, "headers_llm_model", ""),
        )
        return cls(
            model=settings.headers_llm_model,
            fallback_model=fallback_model,
            timeout_s=settings.headers_llm_timeout_s,
            max_input_tokens=settings.headers_llm_max_input_tokens,
            cache_dir=settings.headers_llm_cache_dir,
            chunking=str(chunking or "auto").strip().lower() or "auto",
            chunk_target_tokens=int(
                getattr(settings, "headers_llm_chunk_target_tokens", 35_000)
            ),
            retry_max=int(getattr(settings, "headers_llm_retry_max", 3)),
            backoff_s=float(getattr(settings, "headers_llm_backoff_s", 2.0)),
            suppress_toc=settings.headers_suppress_toc,
            suppress_running=settings.headers_suppress_running,
            normalize_confusables=settings.headers_normalize_confusables,
            strict_invariants=settings.headers_strict_invariants,
            title_only_reanchor=settings.headers_title_only_reanchor,
        )


@dataclass(slots=True)
class _AttemptOutcome:
    ok: bool
    headers: List[HeaderItem]
    status: str
    reason: str | None = None
    raw: List[str] = field(default_factory=list)
    fenced: List[str] = field(default_factory=list)
    attempts: int = 1
    duration_s: float | None = None


_RETRIABLE_REASONS = {"missing_fence", "invalid_json", "empty"}


def _serialise_attempt(summary: AttemptSummary) -> dict:
    payload = {
        "rung": summary.rung,
        "model": summary.model,
        "status": summary.status,
    }
    if summary.reason:
        payload["reason"] = summary.reason
    if summary.chunk_count:
        payload["chunk_count"] = summary.chunk_count
    if summary.retries:
        payload["retries"] = summary.retries
    if summary.duration_s is not None:
        payload["duration_s"] = summary.duration_s
    return payload


async def _invoke_single(
    client: LLMClient,
    pages: Sequence[str],
    *,
    tighten: bool,
    chunk_index: int | None,
    chunk_total: int | None,
    max_tokens: int,
    config: HeadersConfig,
) -> _AttemptOutcome:
    prompt = build_prompt(pages, tighten=tighten, chunk_index=chunk_index, chunk_total=chunk_total)
    raw_responses: List[str] = []
    fenced_blocks: List[str] = []
    reason: str | None = None
    start = time.perf_counter()

    for attempt in range(1, config.retry_max + 2):
        try:
            response = await client.complete(
                prompt,
                "\n\n".join(pages),
                params={"max_tokens": max_tokens},
            )
        except OpenRouterError as exc:
            status_code = getattr(exc, "status_code", None)
            reason = "timeout" if status_code in {408, 504} else "error"
            if attempt <= config.retry_max:
                await asyncio.sleep(config.backoff_s)
                continue
            duration = time.perf_counter() - start
            return _AttemptOutcome(
                ok=False,
                headers=[],
                status="failed",
                reason=reason,
                raw=raw_responses,
                fenced=fenced_blocks,
                attempts=attempt,
                duration_s=duration,
            )
        raw_text = response.text.strip()
        raw_responses.append(raw_text)
        if not raw_text:
            reason = "empty"
        elif raw_text.upper() == "ABORT":
            reason = "abort_token"
        else:
            block = extract_fenced_simpleheaders_block(raw_text)
            if block is None:
                reason = "bad_label" if detect_bad_label(raw_text) else "missing_fence"
            else:
                fenced_blocks.append(block)
                try:
                    headers = parse_fenced_payload(raw_text)
                except ValueError as exc:
                    reason = exc.args[0] if exc.args else "invalid_json"
                else:
                    if not headers:
                        reason = "empty"
                    else:
                        duration = time.perf_counter() - start
                        return _AttemptOutcome(
                            ok=True,
                            headers=headers,
                            status="ok",
                            reason=None,
                            raw=raw_responses,
                            fenced=fenced_blocks,
                            attempts=attempt,
                            duration_s=duration,
                        )
        if reason not in _RETRIABLE_REASONS or attempt > config.retry_max:
            break
        await asyncio.sleep(config.backoff_s)

    duration = time.perf_counter() - start
    return _AttemptOutcome(
        ok=False,
        headers=[],
        status="failed",
        reason=reason,
        raw=raw_responses,
        fenced=fenced_blocks,
        attempts=min(config.retry_max + 1, len(raw_responses) or 1),
        duration_s=duration,
    )


async def _invoke_chunked(
    client: LLMClient,
    chunks: List[List[ChunkPage]],
    *,
    config: HeadersConfig,
) -> _AttemptOutcome:
    aggregated_headers: List[List[HeaderItem]] = []
    raw: List[str] = []
    fenced: List[str] = []
    start = time.perf_counter()
    completion_count = 0
    order_offset = 0

    for index, chunk in enumerate(chunks, start=1):
        pages = [page.text for page in chunk]
        outcome = await _invoke_single(
            client,
            pages,
            tighten=True,
            chunk_index=index,
            chunk_total=len(chunks),
            max_tokens=config.max_input_tokens,
            config=config,
        )
        raw.extend(outcome.raw)
        fenced.extend(outcome.fenced)
        completion_count += max(1, len(outcome.raw))
        if not outcome.ok:
            return _AttemptOutcome(
                ok=False,
                headers=[],
                status="failed",
                reason=outcome.reason,
                raw=raw,
                fenced=fenced,
                attempts=outcome.attempts,
                duration_s=time.perf_counter() - start,
            )
        adjusted: List[HeaderItem] = []
        for local_index, header in enumerate(outcome.headers):
            item = HeaderItem(
                number=header.number,
                title=header.title,
                level=header.level,
                page=header.page or chunk[0].index,
                order=order_offset + local_index,
                source="llm",
                meta={"chunk": index},
            )
            adjusted.append(item)
        order_offset += len(adjusted)
        aggregated_headers.append(adjusted)

    stitched = stitch_chunks(aggregated_headers)
    duration = time.perf_counter() - start
    return _AttemptOutcome(
        ok=True,
        headers=stitched,
        status="ok",
        reason=None,
        raw=raw,
        fenced=fenced,
        attempts=completion_count,
        duration_s=duration,
    )


def _normalise_pages(pages: Sequence[object]) -> List[str]:
    normalised: List[str] = []
    for page in pages:
        if isinstance(page, str):
            text = page
        elif hasattr(page, "text"):
            text = str(getattr(page, "text"))
        elif isinstance(page, dict):
            text = str(page.get("text", ""))
        else:
            text = str(page)
        normalised.append(text)
    return normalised


async def extract_headers(
    pages: Sequence[object],
    *,
    config: HeadersConfig | None = None,
    llm_client: LLMClient | None = None,
    fallback_client: LLMClient | None = None,
    legacy_locator: Callable[[Sequence[str]], List[HeaderItem]] | None = None,
) -> ExtractHeadersResult:
    """Return headers discovered using the retry/fallback ladder."""

    if not pages:
        return ExtractHeadersResult(
            ok=False,
            headers=[],
            attempts=[],
            error="no_pages",
            meta={},
        )

    config = config or HeadersConfig.from_env()
    ladder_attempts: List[AttemptSummary] = []
    raw_responses: List[str] = []
    fenced_blocks: List[str] = []
    pages_text = _normalise_pages(pages)

    primary_client = llm_client or LLMClient(model=config.model, timeout_s=config.timeout_s)
    secondary_client = fallback_client or (
        LLMClient(model=config.fallback_model, timeout_s=config.timeout_s)
        if config.fallback_model and config.fallback_model != config.model
        else None
    )

    # Attempt 1: primary prompt
    outcome = await _invoke_single(
        primary_client,
        pages_text,
        tighten=False,
        chunk_index=None,
        chunk_total=None,
        max_tokens=config.max_input_tokens,
        config=config,
    )
    raw_responses.extend(outcome.raw)
    fenced_blocks.extend(outcome.fenced)
    ladder_attempts.append(
        AttemptSummary(
            rung="primary",
            model=primary_client.model,
            status="ok" if outcome.ok else "failed",
            reason=outcome.reason,
            chunk_count=0,
            retries=max(0, outcome.attempts - 1),
            duration_s=outcome.duration_s,
        )
    )
    if outcome.ok:
        headers = normalize_headers(
            outcome.headers,
            suppress_toc=config.suppress_toc,
            suppress_running=config.suppress_running,
            normalize_confusables=config.normalize_confusables,
        )
        meta = {
            "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
            "raw_responses": raw_responses,
            "fenced_blocks": fenced_blocks,
        }
        return ExtractHeadersResult(ok=True, headers=headers, attempts=ladder_attempts, meta=meta)

    # Attempt 2: tightened prompt
    outcome = await _invoke_single(
        primary_client,
        pages_text,
        tighten=True,
        chunk_index=None,
        chunk_total=None,
        max_tokens=int(max(1024, config.max_input_tokens * 0.75)),
        config=config,
    )
    raw_responses.extend(outcome.raw)
    fenced_blocks.extend(outcome.fenced)
    ladder_attempts.append(
        AttemptSummary(
            rung="primary_tight",
            model=primary_client.model,
            status="ok" if outcome.ok else "failed",
            reason=outcome.reason,
            chunk_count=0,
            retries=max(0, outcome.attempts - 1),
            duration_s=outcome.duration_s,
        )
    )
    if outcome.ok:
        headers = normalize_headers(
            outcome.headers,
            suppress_toc=config.suppress_toc,
            suppress_running=config.suppress_running,
            normalize_confusables=config.normalize_confusables,
        )
        meta = {
            "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
            "raw_responses": raw_responses,
            "fenced_blocks": fenced_blocks,
        }
        return ExtractHeadersResult(ok=True, headers=headers, attempts=ladder_attempts, meta=meta)

    # Attempt 3: chunked extraction if permitted
    chunk_required = config.chunking == "force"
    if config.chunking in {"auto", "force"}:
        chunks = make_chunks([
            {"page": idx + 1, "text": text}
            for idx, text in enumerate(pages_text)
        ], config.chunk_target_tokens)
        if chunk_required or len(chunks) > 1:
            chunk_outcome = await _invoke_chunked(primary_client, chunks, config=config)
            raw_responses.extend(chunk_outcome.raw)
            fenced_blocks.extend(chunk_outcome.fenced)
            ladder_attempts.append(
                AttemptSummary(
                    rung="chunk_primary",
                    model=primary_client.model,
                    status="ok" if chunk_outcome.ok else "failed",
                    reason=chunk_outcome.reason,
                    chunk_count=len(chunks),
                    retries=max(0, chunk_outcome.attempts - 1),
                    duration_s=chunk_outcome.duration_s,
                )
            )
            if chunk_outcome.ok:
                headers = normalize_headers(
                    chunk_outcome.headers,
                    suppress_toc=config.suppress_toc,
                    suppress_running=config.suppress_running,
                    normalize_confusables=config.normalize_confusables,
                )
                meta = {
                    "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
                    "raw_responses": raw_responses,
                    "fenced_blocks": fenced_blocks,
                    "chunk_count": len(chunks),
                }
                return ExtractHeadersResult(
                    ok=True,
                    headers=headers,
                    attempts=ladder_attempts,
                    meta=meta,
                )
    else:
        chunks = []

    # Fallback F1: secondary model
    if secondary_client is not None:
        outcome = await _invoke_single(
            secondary_client,
            pages_text,
            tighten=True,
            chunk_index=None,
            chunk_total=None,
            max_tokens=config.max_input_tokens,
            config=config,
        )
        raw_responses.extend(outcome.raw)
        fenced_blocks.extend(outcome.fenced)
        ladder_attempts.append(
            AttemptSummary(
                rung="fallback_model",
                model=secondary_client.model,
                status="ok" if outcome.ok else "failed",
                reason=outcome.reason,
                chunk_count=0,
                retries=max(0, outcome.attempts - 1),
                duration_s=outcome.duration_s,
            )
        )
        if outcome.ok:
            headers = normalize_headers(
                outcome.headers,
                suppress_toc=config.suppress_toc,
                suppress_running=config.suppress_running,
                normalize_confusables=config.normalize_confusables,
            )
            meta = {
                "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
                "raw_responses": raw_responses,
                "fenced_blocks": fenced_blocks,
            }
            return ExtractHeadersResult(ok=True, headers=headers, attempts=ladder_attempts, meta=meta)

    # Fallback F2: legacy locator
    locator = legacy_locator or legacy_outline
    legacy_headers = locator(pages_text)
    ladder_attempts.append(
        AttemptSummary(
            rung="fallback_legacy",
            model="legacy",
            status="ok" if legacy_headers else "failed",
            reason=None if legacy_headers else "empty",
            chunk_count=0,
            retries=0,
            duration_s=None,
        )
    )
    if legacy_headers:
        headers = normalize_headers(
            legacy_headers,
            suppress_toc=config.suppress_toc,
            suppress_running=config.suppress_running,
            normalize_confusables=config.normalize_confusables,
        )
        meta = {
            "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
            "raw_responses": raw_responses,
            "fenced_blocks": fenced_blocks,
            "source": "legacy",
        }
        return ExtractHeadersResult(ok=True, headers=headers, attempts=ladder_attempts, meta=meta)

    meta = {
        "attempts": [_serialise_attempt(entry) for entry in ladder_attempts],
        "raw_responses": raw_responses,
        "fenced_blocks": fenced_blocks,
    }
    return ExtractHeadersResult(
        ok=False,
        headers=[],
        attempts=ladder_attempts,
        error="extraction_failed",
        meta=meta,
    )


__all__ = ["HeadersConfig", "extract_headers", "HeaderItem", "AttemptSummary", "ExtractHeadersResult"]
