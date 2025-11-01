"""Coordinator for LLM-backed and native header extraction flows."""

from __future__ import annotations

import logging
import re
import time
from typing import Iterable, Mapping, Sequence

from sqlmodel import Session

import backend.config as app_config
from backend.config import Settings
from backend.models import Document, DocumentArtifactType

from .artifact_store import PARSER_VERSION, get_cached_artifact, store_artifact
from .header_locate_vector import locate_headers_with_vectors
from .header_locator import locate_headers_in_lines
from .headers_llm_strict import align_headers_llm_strict
from .headers_sequential import number_key
from .pdf_headers_llm_full import LLMFullHeadersResult, get_headers_llm_full
from .pdf_native import collect_line_metrics
from .section_chunking import single_chunks_from_headers
from ..utils.logging import configure_logging
from ..utils.trace import HeaderTracer

LOGGER = configure_logging().getChild(__name__)


def _format_llm_failure(exc: Exception) -> str:
    """Return a concise message describing an LLM extraction failure."""

    text = str(exc).strip()
    if not text:
        text = exc.__class__.__name__

    match = re.search(r"\b(\d{3})\b", text)
    if match:
        code = match.group(1)
        if code in {"401", "403"}:
            return (
                "LLM header extraction unavailable (HTTP {code}). "
                "Verify the OpenRouter API key and referer configuration."
            ).format(code=code)
        if code == "429":
            return (
                "LLM header extraction temporarily unavailable (HTTP 429). "
                "Rate limit exceeded; retry later."
            )
        return "LLM header extraction unavailable (HTTP {code}).".format(code=code)

    return "LLM header extraction unavailable."


async def extract_headers_and_chunks(
    document_bytes: bytes,
    *,
    settings: Settings,
    native_headers: Sequence[Mapping[str, object]] | None = None,
    metadata: Mapping[str, object] | None = None,
    session: Session | None = None,
    document: Document | None = None,
    want_trace: bool = False,
) -> tuple[dict, HeaderTracer | None]:
    """Return located headers and section ranges for the provided document."""

    trace_requested = want_trace or app_config.HEADERS_TRACE
    tracer: HeaderTracer | None = HeaderTracer(out_dir=app_config.HEADERS_TRACE_DIR)

    start_time = time.perf_counter()
    if tracer:
        tracer.ev(
            "start_run",
            mode=settings.headers_mode,
            file_id=getattr(document, "id", None),
            cfg={
                "suppress_toc": settings.headers_suppress_toc,
                "suppress_running": settings.headers_suppress_running,
            },
            metadata=dict(metadata or {}),
        )
        if native_headers:
            tracer.ev(
                "native_expectations",
                expected=[
                    {
                        "text": str(entry.get("text", "")).strip(),
                        "number": (entry.get("number") or None),
                        "level": int(entry.get("level") or 1),
                    }
                    for entry in native_headers
                ],
                count=len(native_headers),
            )

    lines, excluded_pages, doc_hash = collect_line_metrics(
        document_bytes,
        metadata,
        suppress_toc=settings.headers_suppress_toc,
        suppress_running=settings.headers_suppress_running,
        tracer=tracer,
    )

    located_headers: list[dict] = []
    mode_used = "llm_full"
    messages: list[str] = []
    fenced_text: str | None = None

    doc_id = document.id if document and document.id is not None else None
    cache_inputs = {
        "doc_hash": doc_hash,
        "parser_version": PARSER_VERSION,
        "headers_mode": settings.headers_mode.lower(),
        "suppress_toc": settings.headers_suppress_toc,
        "suppress_running": settings.headers_suppress_running,
        "metadata": dict(metadata or {}),
        "header_locator_rev": "2025-10-31-seq-source-order",
    }

    if session is not None and doc_id is not None:
        cached = get_cached_artifact(
            session=session,
            document_id=doc_id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            key=settings.headers_mode.lower(),
            inputs=cache_inputs,
        )
        if cached is not None:
            payload = dict(cached.body)
            located = list(payload.get("headers", []))
            sections = list(payload.get("sections", []))
            messages = list(payload.get("messages", []))
            mode_used = payload.get("mode", "cache")
            fenced_text = payload.get("fenced_text")
            matched_titles = {str(item.get("text", "")).strip() for item in located}
            expected_titles = [str(item.get("text", "")) for item in (native_headers or [])]
            unresolved = [
                title for title in expected_titles if title and title not in matched_titles
            ]
            elapsed = time.perf_counter() - start_time
            if tracer:
                tracer.ev(
                    "llm_outline_received",
                    count=len(located),
                    headers=list(payload.get("headers", [])),
                )
                tracer.ev(
                    "final_outline",
                    headers=located,
                    sections=sections,
                    mode=mode_used,
                    messages=messages,
                    elapsed_s=elapsed,
                )
                tracer.ev(
                    "end_run",
                    elapsed_s=elapsed,
                    total_headers=len(located),
                    unresolved=unresolved,
                    mode="cache",
                    doc_hash=doc_hash,
                )
                tracer.flush_jsonl()
                LOGGER.info("[headers] Trace written: %s", tracer.path)
                LOGGER.info("[headers] Summary written: %s", tracer.summary_path)
            return {
                "headers": located,
                "sections": sections,
                "mode": mode_used,
                "lines": lines,
                "doc_hash": doc_hash,
                "excluded_pages": sorted(excluded_pages),
                "messages": messages,
                "fenced_text": fenced_text,
            }, tracer

    if settings.headers_mode.lower() == "llm_full":
        try:
            llm_result: LLMFullHeadersResult = await get_headers_llm_full(
                lines,
                doc_hash,
                settings=settings,
                excluded_pages=excluded_pages,
            )
            llm_headers = llm_result.headers or []
            fenced_text = llm_result.combined_fenced()
            strict_attempted = False
            vector_attempted = False
            if settings.headers_llm_strict and llm_headers:
                strict_attempted = True
                strict_resolved = align_headers_llm_strict(
                    llm_headers,
                    lines,
                    tracer=tracer,
                )
                if strict_resolved:
                    located_headers = [
                        {
                            "text": str(item["header"].get("text", "")).strip(),
                            "number": item["header"].get("number"),
                            "level": int(item["header"].get("level", 1)),
                            "page": int(item["line"].get("page", 0)),
                            "line_idx": int(item["line"].get("line_idx", 0)),
                            "global_idx": int(item["line"].get("global_idx", 0)),
                            "source_idx": int(item["header"].get("_orig_index", -1)),
                            "strategy": item.get("strategy"),
                            "score": item.get("score"),
                        }
                        for item in strict_resolved
                    ]
                    mode_used = "llm_strict"
            if not located_headers and settings.header_locate_use_embeddings:
                try:
                    vector_attempted = True
                    located_headers = locate_headers_with_vectors(
                        session=session,
                        document_id=doc_id or 0,
                        simple_headers=llm_headers,
                        lines=lines,
                        settings=settings,
                        excluded_pages=excluded_pages,
                        tracer=tracer,
                        doc_hash=doc_hash,
                        write_trace_json=trace_requested,
                    )
                    if located_headers:
                        mode_used = "llm_vector"
                except Exception as exc:  # pragma: no cover - defensive log
                    LOGGER.warning("Vector header locator failed: %s", exc, exc_info=True)
                    if tracer:
                        tracer.ev(
                            "fallback_triggered",
                            method="vector",
                            reason="exception",
                            message=str(exc),
                        )
                    messages.append("Vector header locator unavailable; using sequential alignment.")
                    located_headers = []

            if not located_headers:
                located_headers = locate_headers_in_lines(
                    llm_headers,
                    lines,
                    excluded_pages=excluded_pages,
                    tracer=tracer,
                )
                if vector_attempted and tracer:
                    tracer.ev(
                        "fallback_triggered",
                        method="vector",
                        reason="no_candidates",
                    )
                if strict_attempted and tracer:
                    tracer.ev(
                        "fallback_triggered",
                        method="llm_strict",
                        reason="no_candidates",
                    )
            if tracer:
                tracer.ev(
                    "llm_outline_received",
                    count=len(llm_headers),
                    headers=llm_headers,
                )
                if app_config.HEADERS_TRACE_EMBED_RESPONSE:
                    tracer.ev(
                        "llm_raw_response",
                        parts=llm_result.raw_responses,
                        fenced=llm_result.fenced_blocks,
                    )
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            LOGGER.warning("LLM header extraction failed: %s", exc)
            located_headers = []
            messages.append(_format_llm_failure(exc))
            mode_used = "llm_full_error"
            if tracer:
                tracer.ev("llm_outline_received", count=0, headers=[])
                tracer.ev(
                    "fallback_triggered",
                    method="llm_full",
                    reason="exception",
                    message=str(exc),
                )
    else:
        mode_used = "llm_disabled"
        messages.append("LLM header extraction is disabled by configuration.")
        if tracer:
            tracer.ev(
                "fallback_triggered",
                method="llm_disabled",
                reason="configuration",
            )
            tracer.ev("llm_outline_received", count=0, headers=[])

    located_headers, sections = _enforce_header_sequence(
        located_headers, lines, tracer=tracer
    )

    if session is not None and doc_id is not None:
        store_artifact(
            session=session,
            document_id=doc_id,
            artifact_type=DocumentArtifactType.HEADER_TREE,
            key=settings.headers_mode.lower(),
            inputs=cache_inputs,
            body={
                "headers": located_headers,
                "sections": sections,
                "mode": mode_used,
                "messages": messages,
                "doc_hash": doc_hash,
                "fenced_text": fenced_text,
            },
        )

    matched_titles = {str(item.get("text", "")).strip() for item in located_headers}
    expected_titles = [str(item.get("text", "")) for item in (native_headers or [])]
    unresolved = [title for title in expected_titles if title and title not in matched_titles]

    elapsed = time.perf_counter() - start_time
    if tracer:
        tracer.ev(
            "final_outline",
            headers=located_headers,
            sections=sections,
            mode=mode_used,
            messages=messages,
            elapsed_s=elapsed,
        )
        tracer.ev(
            "end_run",
            elapsed_s=elapsed,
            total_headers=len(located_headers),
            unresolved=unresolved,
            mode=mode_used,
            doc_hash=doc_hash,
        )
        trace_path = tracer.flush_jsonl()
        LOGGER.info("[headers] Trace written: %s", trace_path)
        LOGGER.info("[headers] Summary written: %s", tracer.summary_path)

    return {
        "headers": located_headers,
        "sections": sections,
        "mode": mode_used,
        "lines": lines,
        "doc_hash": doc_hash,
        "excluded_pages": sorted(excluded_pages),
        "messages": messages,
        "fenced_text": fenced_text,
    }, tracer


def _enforce_header_sequence(
    headers: Sequence[Mapping[str, object]],
    lines: Sequence[Mapping[str, object]],
    *,
    tracer: HeaderTracer | None = None,
) -> tuple[list[dict], list[dict]]:
    """Ensure located headers follow sequential numbering when possible."""

    if not headers:
        return [], []

    def _order_key(header: Mapping[str, object]) -> tuple:
        number = header.get("number")
        order = number_key(str(number)) if number else [-1]
        source_idx = int(header.get("source_idx", -1))
        if source_idx >= 0:
            return (
                source_idx,
                *order,
                int(header.get("level", 0)),
                int(header.get("global_idx", 0)),
            )
        return (*order, int(header.get("level", 0)), int(header.get("global_idx", 0)))

    working_headers = [
        {
            "text": str(header.get("text", "")).strip(),
            "number": (header.get("number") or None),
            "level": int(header.get("level") or 1),
            "page": int(header.get("page") or 0),
            "line_idx": int(header.get("line_idx") or 0),
            "global_idx": int(header.get("global_idx") or 0),
            "source_idx": int(header.get("source_idx", -1)),
        }
        for header in headers
    ]
    working_headers.sort(key=lambda item: item.get("global_idx", 0))
    working_headers.sort(key=_order_key)

    sections = single_chunks_from_headers(working_headers, lines)

    iteration = 0
    while True:
        gaps = _identify_missing_headers(working_headers)
        if not gaps:
            break
        iteration += 1
        if tracer:
            tracer.ev(
                "monotonic_violation",
                iteration=iteration,
                gaps=[
                    {
                        "after_index": gap.get("after_index"),
                        "components": gap.get("components"),
                        "level": gap.get("level"),
                    }
                    for gap in gaps
                ],
            )

        index_by_global = {
            int(line.get("global_idx", -1)): idx for idx, line in enumerate(lines)
        }
        inserted = False

        for gap in gaps:
            after_index = gap.get("after_index")
            if after_index is None or after_index < 0:
                continue
            if after_index >= len(sections):
                continue

            chunk = sections[after_index]
            candidate = _find_header_in_chunk(
                chunk,
                lines,
                gap.get("components", ()),
                index_by_global,
                gap.get("level"),
            )

            if not candidate:
                continue

            if any(
                int(existing.get("global_idx", -1))
                == candidate.get("global_idx", -2)
                for existing in working_headers
            ):
                continue

            insert_position = int(gap.get("insert_position", after_index + 1))
            insert_position = max(0, min(insert_position, len(working_headers)))
            working_headers.insert(insert_position, candidate)
            working_headers.sort(key=lambda item: item.get("global_idx", 0))
            sections = single_chunks_from_headers(working_headers, lines)
            inserted = True
            if tracer:
                tracer.ev(
                    "anchor_resolved",
                    target=candidate.get("text"),
                    page=candidate.get("page"),
                    line_idx=candidate.get("line_idx"),
                    global_idx=candidate.get("global_idx"),
                    monotonic_ok=True,
                    method="gap_fill",
                )
            break

        if not inserted:
            if tracer:
                tracer.ev(
                    "fallback_triggered",
                    method="gap_fill",
                    reason="unresolved",
                )
            break

    working_headers.sort(key=lambda item: item.get("global_idx", 0))
    working_headers.sort(key=_order_key)

    for entry in working_headers:
        entry.pop("source_idx", None)

    return working_headers, sections


def _identify_missing_headers(headers: Sequence[Mapping[str, object]]) -> list[dict]:
    """Return metadata about numbering gaps detected in located headers."""

    missing: list[dict] = []
    expected_by_key: dict[tuple, int] = {}
    last_index_by_key: dict[tuple, int] = {}
    components_cache: dict[int, list[dict]] = {}

    for idx, header in enumerate(headers):
        components = _extract_components(header.get("number"))
        components_cache[idx] = components
        if not components:
            continue

        prefix_components = components[:-1]
        last_component = components[-1]
        kind = last_component.get("kind")
        value = last_component.get("value")

        if kind not in {"numeric", "alpha"} or value is None:
            key = (_prefix_key(prefix_components), kind)
            last_index_by_key[key] = idx
            continue

        key = (_prefix_key(prefix_components), kind)
        expected = expected_by_key.get(key)
        last_index = last_index_by_key.get(key)

        if expected is not None and value > expected:
            template_component = None
            if last_index is not None:
                previous_components = components_cache.get(last_index) or []
                if previous_components:
                    template_component = previous_components[-1]
            if template_component is None:
                template_component = last_component

            prefix = [dict(component) for component in prefix_components]
            prev_level = (
                int(headers[last_index].get("level") or 1)
                if last_index is not None
                else int(header.get("level") or 1)
            )

            for missing_value in _value_range(expected, value):
                missing_component = _build_component(
                    missing_value,
                    kind,
                    template_component,
                )
                missing.append(
                    {
                        "components": prefix + [missing_component],
                        "after_index": last_index,
                        "insert_position": (last_index + 1) if last_index is not None else 0,
                        "level": prev_level,
                    }
                )

        expected_by_key[key] = value + 1
        last_index_by_key[key] = idx

    return missing


def _value_range(start: int, stop: int) -> Iterable[int]:
    """Yield the integer values that should appear between start and stop."""

    for value in range(start, stop):
        yield value


def _prefix_key(components: Sequence[Mapping[str, object]]) -> tuple:
    """Create a hashable key for a sequence prefix."""

    return tuple((component.get("kind"), component.get("value")) for component in components)


def _build_component(
    value: int,
    kind: str,
    template: Mapping[str, object] | None,
) -> dict:
    """Create a component description following the provided template."""

    template_raw = str(template.get("raw", "")) if template else ""

    if kind == "numeric":
        width = len(template_raw) if template_raw.isdigit() else 0
        raw = str(value).zfill(width) if width else str(value)
        normalized = str(value)
    elif kind == "alpha":
        normalized = _int_to_alpha(value)
        raw = normalized
        if template_raw.islower():
            raw = raw.lower()
            normalized = normalized.upper()
    else:
        raw = str(value)
        normalized = raw

    return {
        "raw": raw,
        "normalized": normalized,
        "kind": kind,
        "value": value,
    }


def _extract_components(number: object | None) -> list[dict]:
    """Split a header number into comparable components."""

    if not number:
        return []

    text = str(number)
    raw_components = re.findall(r"[A-Za-z]+|\d+", text)
    components: list[dict] = []

    for component in raw_components:
        if component.isdigit():
            value = int(component)
            components.append(
                {
                    "raw": component,
                    "normalized": str(value),
                    "kind": "numeric",
                    "value": value,
                }
            )
            continue

        if component.isalpha():
            value = _alpha_to_int(component)
            components.append(
                {
                    "raw": component,
                    "normalized": _int_to_alpha(value),
                    "kind": "alpha",
                    "value": value,
                }
            )
            continue

        components.append(
            {
                "raw": component,
                "normalized": component,
                "kind": None,
                "value": None,
            }
        )

    return components


def _alpha_to_int(value: str) -> int:
    """Convert alphabetical enumeration to its integer representation."""

    total = 0
    for char in value.upper():
        if "A" <= char <= "Z":
            total = total * 26 + (ord(char) - ord("A") + 1)
    return total


def _int_to_alpha(value: int) -> str:
    """Convert an integer to alphabetical enumeration (A, B, ..., AA)."""

    if value <= 0:
        return "A"

    chars: list[str] = []
    remaining = value
    while remaining > 0:
        remaining -= 1
        remaining, remainder = divmod(remaining, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def _find_header_in_chunk(
    chunk: Mapping[str, object],
    lines: Sequence[Mapping[str, object]],
    components: Sequence[Mapping[str, object]],
    index_by_global: Mapping[int, int],
    fallback_level: int | None,
) -> dict | None:
    """Search a section chunk for a header matching the expected numbering."""

    if not components:
        return None

    pattern = _build_number_pattern(components)
    if pattern is None:
        return None

    start_global = int(chunk.get("start_global_idx", 0))
    end_global = int(chunk.get("end_global_idx", start_global))
    start_idx = index_by_global.get(start_global, 0)
    end_idx = index_by_global.get(end_global, start_idx)

    for idx in range(start_idx, end_idx + 1):
        line = lines[idx]
        text = str(line.get("text", ""))
        stripped = text.lstrip()
        match = pattern.match(stripped)
        if not match:
            continue

        remainder = stripped[match.end() :].lstrip(" -.):\t")
        header_text = remainder or stripped

        level = int(chunk.get("level") or fallback_level or 1)

        return {
            "text": header_text,
            "number": _components_to_number(components),
            "level": level,
            "page": int(line.get("page") or 0),
            "line_idx": int(line.get("line_idx") or 0),
            "global_idx": int(line.get("global_idx") or 0),
        }

    return None


def _build_number_pattern(
    components: Sequence[Mapping[str, object]]
) -> re.Pattern[str] | None:
    """Compile a regex pattern matching the expected numbering."""

    if not components:
        return None

    parts: list[str] = []
    for component in components:
        raw = str(component.get("raw", ""))
        normalized = str(component.get("normalized", raw))
        kind = component.get("kind")

        if kind == "numeric":
            parts.append(rf"0*{re.escape(normalized)}")
        else:
            token = raw or normalized
            parts.append(re.escape(token))

    separator = r"(?:[\s\.\-\)\(]*?)"
    joined = separator.join(parts)
    pattern = rf"^\s*[\(\[]?\s*{joined}(?:\b|[\.).\-\s:])"

    return re.compile(pattern, re.IGNORECASE)


def _components_to_number(components: Sequence[Mapping[str, object]]) -> str:
    """Convert components back into a dotted numbering string."""

    values: list[str] = []
    for component in components:
        normalized = str(component.get("normalized") or "")
        if not normalized:
            continue
        values.append(normalized)
    return ".".join(values) if values else ""


__all__ = ["extract_headers_and_chunks"]
