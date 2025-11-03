"""Vector-based header locator integrating lexical and layout cues."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np
from sqlmodel import Session, delete

from backend.config import (
    HEADER_LOCATE_FUSE_WEIGHTS,
    HEADER_LOCATE_MIN_COSINE,
    HEADER_LOCATE_MIN_LEXICAL,
    HEADER_LOCATE_PREFER_LAST_MATCH,
    Settings,
)
from backend.models import HeaderAnchor

from ..utils.trace import HeaderTracer
from .embeddings import EmbeddingsClient
from .vector_index import (
    build_line_windows,
    embed_windows,
    export_trace,
    score_candidates,
)


def _canonical_headers(headers: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    canonical: list[dict[str, object]] = []
    for index, header in enumerate(headers):
        title = str(header.get("text", "")).strip()
        if not title:
            continue
        canonical.append(
            {
                "uid": str(header.get("uid") or index + 1),
                "text": title,
                "number": (header.get("number") or None),
                "level": int(header.get("level") or 1),
            }
        )
    return canonical


def locate_headers_with_vectors(
    *,
    session: Session | None,
    document_id: int,
    simple_headers: Sequence[Mapping[str, object]],
    lines: Sequence[Mapping[str, object]],
    settings: Settings,
    excluded_pages: Iterable[int] | None = None,
    tracer: HeaderTracer | None = None,
    doc_hash: str | None = None,
    embeddings_client: EmbeddingsClient | None = None,
    write_trace_json: bool = False,
) -> list[dict[str, object]]:
    """Return located headers using the vector locator."""

    if tracer is not None:
        tracer.log_call(f"{__name__}.locate_headers_with_vectors")

    canonical = _canonical_headers(simple_headers)
    if not canonical:
        return []

    windows = build_line_windows(lines, excluded_pages=excluded_pages)
    if not windows:
        return []

    embedder = embeddings_client or EmbeddingsClient(settings)
    cache_key = f"{doc_hash or document_id}-windows"
    window_embeddings = embed_windows(windows, embedder, cache_key=cache_key)
    header_texts = [entry["text"] for entry in canonical]
    header_embeddings = (
        embedder.embed_batch(header_texts) if header_texts else np.zeros((0, 0), dtype=np.float32)
    )

    weights = settings.header_locate_fuse_weights or HEADER_LOCATE_FUSE_WEIGHTS
    thresholds = (
        settings.header_locate_min_lexical or HEADER_LOCATE_MIN_LEXICAL,
        settings.header_locate_min_cosine or HEADER_LOCATE_MIN_COSINE,
    )
    prefer_last = settings.header_locate_prefer_last_match or HEADER_LOCATE_PREFER_LAST_MATCH

    resolved: list[dict[str, object]] = []
    trace_payload: list[dict[str, object]] = []
    previous_anchor = -1

    if session is not None:
        session.exec(delete(HeaderAnchor).where(HeaderAnchor.document_id == document_id))

    for index, entry in enumerate(canonical):
        header_vector = (
            header_embeddings[index]
            if index < header_embeddings.shape[0]
            else np.zeros(window_embeddings.shape[1] if window_embeddings.size else 0)
        )
        candidates = score_candidates(
            entry["text"],
            entry["level"],
            windows,
            window_embeddings,
            header_vector,
            weights=weights,
            thresholds=thresholds,
            prefer_last=prefer_last,
        )

        diag_candidates: list[dict[str, object]] = []
        for rank, candidate in enumerate(candidates[:3], start=1):
            diag_candidates.append(
                {
                    "rank": rank,
                    "page": candidate.window.page,
                    "start": candidate.window.start_line_id,
                    "end": candidate.window.end_line_id,
                    "fused": round(candidate.fused, 3),
                    "lex": round(candidate.lexical, 3),
                    "cos": round(candidate.cosine, 3),
                    "font": round(candidate.font_rank, 3),
                    "y": round(candidate.y_bonus, 3),
                }
            )

        if tracer is not None:
            tracer.ev(
                "vector_candidates",
                header=entry["text"],
                level=entry["level"],
                candidates=diag_candidates,
            )

        anchor = None
        for candidate in candidates:
            if candidate.window.start_line_id > previous_anchor:
                anchor = candidate
                break

        if anchor is None and candidates:
            ascending = sorted(candidates, key=lambda item: item.window.start_line_id)
            for candidate in ascending:
                if candidate.window.start_line_id > previous_anchor:
                    anchor = candidate
                    break

        if anchor is None:
            if tracer is not None:
                tracer.ev(
                    "vector_missing_anchor",
                    header=entry["text"],
                    level=entry["level"],
                )
            continue

        previous_anchor = max(previous_anchor, anchor.window.start_line_id)

        resolved.append(
            {
                "text": entry["text"],
                "number": entry.get("number"),
                "level": entry["level"],
                "page": anchor.window.page,
                "line_idx": anchor.window.start_line_idx,
                "global_idx": anchor.window.start_line_id,
                "source_idx": index,
            }
        )

        if tracer is not None:
            tracer.ev(
                "vector_anchor",
                header=entry["text"],
                level=entry["level"],
                page=anchor.window.page,
                line_idx=anchor.window.start_line_idx,
                global_idx=anchor.window.start_line_id,
                fused=anchor.fused,
                lexical=anchor.lexical,
                cosine=anchor.cosine,
                font=anchor.font_rank,
                y_bonus=anchor.y_bonus,
            )

        if session is not None:
            session.add(
                HeaderAnchor(
                    document_id=document_id,
                    header_uid=str(entry["uid"]),
                    level=entry["level"],
                    title=entry["text"],
                    page=anchor.window.page,
                    y_top=anchor.window.y_top,
                    start_line_id=anchor.window.start_line_id,
                    end_line_id=anchor.window.end_line_id,
                    lexical=anchor.lexical,
                    cosine=anchor.cosine,
                    font_rank=anchor.font_rank,
                    y_bonus=anchor.y_bonus,
                    fused=anchor.fused,
                )
            )

        trace_payload.append(
            {
                "header_uid": str(entry["uid"]),
                "title": entry["text"],
                "level": entry["level"],
                "best": diag_candidates[0] if diag_candidates else None,
                "alts": diag_candidates[1:] if len(diag_candidates) > 1 else [],
            }
        )

    if session is not None:
        session.commit()

    if write_trace_json and trace_payload:
        output_path = settings.export_dir / str(document_id) / "header_locations.json"
        export_trace(output_path, anchors=trace_payload)

    return resolved


__all__ = ["locate_headers_with_vectors"]

