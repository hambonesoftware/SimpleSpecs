"""Helpers for deriving and persisting canonical document sections."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping, Sequence

from sqlalchemy import delete
from sqlmodel import Session, select

from ..models import DocumentSection


def _safe_int(value: object) -> int | None:
    """Return ``value`` coerced to ``int`` when possible."""

    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _normalise_text(text: str) -> str:
    """Return a lower-cased, whitespace-collapsed representation of ``text``."""

    return re.sub(r"\s+", " ", text or "").strip().lower()


def _score_text(query: str, candidate: str) -> float:
    """Return a similarity score between ``query`` and ``candidate``."""

    if not query or not candidate:
        return 0.0

    try:  # pragma: no cover - rapidfuzz optional dependency
        from rapidfuzz import fuzz

        return float(fuzz.partial_ratio(query, candidate))
    except Exception:  # noqa: BLE001 - fallback when rapidfuzz unavailable
        ratio = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
        return float(ratio * 100)


def make_section_key(
    number: str | None,
    title: str,
    *,
    anchor: int | None = None,
) -> str:
    """Return a deterministic identifier for a section."""

    number_part = re.sub(r"\s+", "-", (number or "").strip())
    title_part = re.sub(r"[^a-z0-9]+", "-", _normalise_text(title))
    title_part = re.sub(r"-+", "-", title_part).strip("-") or "section"
    parts: list[str] = []
    if number_part:
        parts.append(number_part)
    parts.append(title_part)
    if anchor is not None:
        parts.append(str(anchor))
    return "::".join(parts)


@dataclass(slots=True)
class _ResolvedHeader:
    """Normalised header representation used when deriving spans."""

    text: str
    number: str | None
    level: int
    page: int | None
    line_idx: int | None
    global_idx: int


def _resolve_headers(
    headers: Sequence[Mapping[str, object]],
    lines: Sequence[Mapping[str, object]],
) -> list[_ResolvedHeader]:
    """Return header entries with reliable ``global_idx`` values."""

    if not headers:
        return []

    line_by_gid: dict[int, Mapping[str, object]] = {}
    lookup_page_line: dict[tuple[int, int], int] = {}
    for line in lines:
        gid = _safe_int(line.get("global_idx"))
        if gid is None:
            continue
        line_by_gid.setdefault(gid, line)
        page = _safe_int(line.get("page"))
        line_idx = _safe_int(line.get("line_idx"))
        if page is not None and line_idx is not None:
            lookup_page_line.setdefault((page, line_idx), gid)

    resolved: list[_ResolvedHeader] = []
    for entry in headers:
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        number_raw = entry.get("number")
        number = str(number_raw).strip() if number_raw not in (None, "") else None
        level = int(entry.get("level") or 1)
        page = _safe_int(entry.get("page"))
        line_idx = _safe_int(entry.get("line_idx"))
        gid = _safe_int(entry.get("global_idx"))

        if gid is None and page is not None and line_idx is not None:
            gid = lookup_page_line.get((page, line_idx))

        if gid is None:
            continue

        resolved.append(
            _ResolvedHeader(
                text=text,
                number=number,
                level=level,
                page=page,
                line_idx=line_idx,
                global_idx=gid,
            )
        )

    if not resolved:
        return []

    # Prefer the last occurrence of each header (TOC/Index exclusion guard).
    dedup: dict[tuple[str | None, str, int], _ResolvedHeader] = {}
    for header in resolved:
        key = (header.number, _normalise_text(header.text), header.level)
        existing = dedup.get(key)
        if existing is None or existing.global_idx <= header.global_idx:
            dedup[key] = header

    resolved = list(dedup.values())
    resolved.sort(
        key=lambda item: (
            item.global_idx,
            item.page if item.page is not None else math.inf,
            item.line_idx if item.line_idx is not None else math.inf,
        )
    )

    # Ensure strictly increasing ``global_idx`` values.
    used: set[int] = set()
    line_order = sorted(line_by_gid)
    for entry in resolved:
        gid = entry.global_idx
        if gid not in used:
            used.add(gid)
            continue

        # Scan forward within a small window to locate the actual heading line.
        start_idx = 0
        if gid in line_by_gid:
            start_idx = line_order.index(gid) + 1
        for candidate_gid in line_order[start_idx:start_idx + 6]:
            line = line_by_gid.get(candidate_gid)
            if line is None:
                continue
            text = _normalise_text(str(line.get("text", "")))
            if text and text == _normalise_text(entry.text):
                gid = candidate_gid
                break
        while gid in used:
            gid += 1
        entry.global_idx = gid
        used.add(gid)

    return resolved

def delete_sections_for_document(
    *,
    session: Session,
    document_id: int,
) -> int:
    """Delete all persisted sections for the given document and commit.

    Returns the number of rows deleted (best-effort; 0 if unavailable).
    """
    result = session.exec(
        delete(DocumentSection).where(DocumentSection.document_id == document_id)
    )
    # SQLAlchemy's rowcount may not always be available depending on dialect.
    try:
        deleted = int(getattr(result, "rowcount", 0) or 0)
    except Exception:  # pragma: no cover - defensive
        deleted = 0
    session.commit()
    return deleted


def build_section_spans(
    simpleheaders: Sequence[Mapping[str, object]],
    lines: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return half-open ranges describing each section span."""

    resolved = _resolve_headers(simpleheaders, lines)
    if not resolved:
        return []

    ordered_lines = sorted(
        (
            line
            for line in lines
            if _safe_int(line.get("global_idx")) is not None
        ),
        key=lambda line: _safe_int(line.get("global_idx")),
    )
    line_index_by_gid = {
        int(line["global_idx"]): index for index, line in enumerate(ordered_lines)
    }

    if ordered_lines:
        last_gid = int(ordered_lines[-1]["global_idx"])
        document_end = last_gid + 1
    else:
        document_end = 0

    spans: list[dict[str, object]] = []
    for position, header in enumerate(resolved):
        start_gid = header.global_idx
        if position + 1 < len(resolved):
            end_gid = resolved[position + 1].global_idx
        else:
            end_gid = document_end
        if end_gid < start_gid:
            end_gid = start_gid

        start_line = ordered_lines[line_index_by_gid.get(start_gid, 0)] if ordered_lines else None
        end_lookup = line_index_by_gid.get(end_gid - 1)
        end_line = ordered_lines[end_lookup] if end_lookup is not None else start_line

        spans.append(
            {
                "section_key": make_section_key(
                    header.number,
                    header.text,
                    anchor=start_gid,
                ),
                "title": header.text,
                "number": header.number,
                "level": header.level,
                "start_global_idx": start_gid,
                "end_global_idx": end_gid,
                "start_page": _safe_int(start_line.get("page")) if start_line else header.page,
                "end_page": _safe_int(end_line.get("page")) if end_line else header.page,
            }
        )

    return spans


def persist_sections(
    *,
    session: Session,
    document_id: int,
    spans: Sequence[Mapping[str, object]],
) -> list[DocumentSection]:
    """Persist the derived section spans for ``document_id``."""

    session.exec(
        delete(DocumentSection).where(DocumentSection.document_id == document_id)
    )
    created: list[DocumentSection] = []
    for span in spans:
        section = DocumentSection(
            document_id=document_id,
            section_key=str(span["section_key"]),
            title=str(span.get("title", "")),
            number=span.get("number"),
            level=int(span.get("level", 1)),
            start_global_idx=int(span.get("start_global_idx", 0)),
            end_global_idx=int(span.get("end_global_idx", 0)),
            start_page=_safe_int(span.get("start_page")),
            end_page=_safe_int(span.get("end_page")),
        )
        session.add(section)
        created.append(section)
    session.commit()
    for section in created:
        session.refresh(section)
    return created


def build_and_store_sections(
    *,
    session: Session,
    document_id: int,
    simpleheaders: Sequence[Mapping[str, object]],
    lines: Sequence[Mapping[str, object]],
) -> list[DocumentSection]:
    """Construct section spans from ``simpleheaders`` and persist them."""

    spans = build_section_spans(simpleheaders, lines)
    if not spans:
        session.exec(
            delete(DocumentSection).where(DocumentSection.document_id == document_id)
        )
        session.commit()
        return []

    return persist_sections(session=session, document_id=document_id, spans=spans)


def chunk_document_by_sections(
    lines: Sequence[Mapping[str, object]],
    spans: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return text chunks bounded by the supplied section spans."""

    if not lines or not spans:
        return []

    by_gid = defaultdict(list)
    for line in lines:
        gid = _safe_int(line.get("global_idx"))
        if gid is None:
            continue
        by_gid[gid].append(str(line.get("text", "")))

    chunks: list[dict[str, object]] = []
    for span in spans:
        start = int(span.get("start_global_idx", 0))
        end = int(span.get("end_global_idx", start))
        collected: list[str] = []
        for gid in range(start, end):
            collected.extend(by_gid.get(gid, []))
        chunks.append(
            {
                "section_key": span.get("section_key"),
                "start_global_idx": start,
                "end_global_idx": end,
                "text": "\n".join(part for part in collected if part.strip()),
            }
        )
    return chunks


def route_query_to_sections(
    *,
    session: Session,
    document_id: int,
    query: str,
    limit: int = 3,
) -> list[str]:
    """Return the top ``limit`` section keys that match ``query``."""

    if not query.strip():
        return []

    statement = select(DocumentSection).where(
        DocumentSection.document_id == document_id
    )
    candidates = session.exec(statement).all()
    scored: list[tuple[float, str]] = []
    for section in candidates:
        label_parts = [section.number or "", section.title]
        label = " ".join(part for part in label_parts if part).strip()
        score = _score_text(query, label)
        if score <= 0:
            continue
        scored.append((score, section.section_key))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [section_key for _, section_key in scored[:limit]]


def search_in_sections(
    *,
    session: Session,
    document_id: int,
    query: str,
    section_keys: Sequence[str],
    lines: Sequence[Mapping[str, object]],
    limit: int = 10,
) -> list[dict[str, object]]:
    """Return the top ``limit`` line matches for ``query`` within ``section_keys``."""

    if not query.strip() or not section_keys:
        return []

    statement = select(DocumentSection).where(
        DocumentSection.document_id == document_id,
        DocumentSection.section_key.in_(section_keys),
    )
    sections = {section.section_key: section for section in session.exec(statement)}
    if not sections:
        return []

    lines_by_gid = {
        int(line["global_idx"]): line
        for line in lines
        if _safe_int(line.get("global_idx")) is not None
    }

    matches: list[dict[str, object]] = []
    for section_key in section_keys:
        section = sections.get(section_key)
        if section is None:
            continue
        for gid in range(section.start_global_idx, section.end_global_idx):
            line = lines_by_gid.get(gid)
            if not line:
                continue
            text = str(line.get("text", "")).strip()
            if not text:
                continue
            score = _score_text(query, text)
            if score <= 0:
                continue
            matches.append(
                {
                    "section_key": section.section_key,
                    "section_title": section.title,
                    "section_number": section.number,
                    "score": score,
                    "text": text,
                    "line_global_idx": gid,
                    "page": _safe_int(line.get("page")),
                    "start_global_idx": section.start_global_idx,
                    "end_global_idx": section.end_global_idx,
                    "start_page": section.start_page,
                    "end_page": section.end_page,
                }
            )

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:limit]


__all__ = [
    "build_and_store_sections",
    "build_section_spans",
    "chunk_document_by_sections",
    "make_section_key",
    "persist_sections",
    "route_query_to_sections",
    "search_in_sections",
    "delete_sections_for_document",  # <-- add this
]

