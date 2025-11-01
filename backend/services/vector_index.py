"""Scoring helpers for the vector-based header locator."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

try:  # pragma: no cover - optional dependency guard
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - fallback without BM25
    BM25Okapi = None  # type: ignore[assignment]

from backend.config import PROJECT_ROOT
from backend.services.embeddings import EmbeddingsClient


TOKEN_PATTERN = re.compile(r"[\w\-']+")
TOC_PATTERN = re.compile(r"\.{2,}\s*\d{1,4}\s*$")


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text or "")]


@dataclass(slots=True)
class LineWindow:
    """Sliding window of document lines used for ranking."""

    text: str
    tokens: list[str]
    page: int
    start_line_id: int
    end_line_id: int
    start_line_idx: int
    end_line_idx: int
    y_top: float | None
    font_max: float | None
    is_toc: bool
    is_index: bool
    is_running: bool


@dataclass(slots=True)
class ScoredCandidate:
    """Scored window candidate for a header."""

    window: LineWindow
    lexical: float
    cosine: float
    font_rank: float
    y_bonus: float
    fused: float


def build_line_windows(
    lines: Sequence[dict],
    *,
    excluded_pages: Iterable[int] | None = None,
) -> list[LineWindow]:
    """Return sliding windows (size 1 and 3) for ``lines``."""

    excluded = {int(page) for page in excluded_pages or ()}
    ordered = sorted(lines, key=lambda item: int(item.get("global_idx", 0)))

    usable: list[dict] = []
    for entry in ordered:
        page = int(entry.get("page", 0) or 0)
        if page in excluded:
            continue
        if not str(entry.get("text", "")).strip():
            continue
        if entry.get("is_toc") or entry.get("is_index"):
            continue
        usable.append(entry)

    windows: list[LineWindow] = []

    def _make_window(chunk: Sequence[dict]) -> LineWindow | None:
        if not chunk:
            return None
        pages = {int(item.get("page", 0) or 0) for item in chunk}
        if len(pages) != 1:
            return None
        text = "\n".join(str(item.get("text", "")) for item in chunk)
        tokens = _tokenize(text)
        if not tokens:
            return None
        tops = [float(item.get("top")) for item in chunk if item.get("top") is not None]
        fonts = [float(item.get("font_size")) for item in chunk if item.get("font_size")]
        return LineWindow(
            text=text,
            tokens=tokens,
            page=pages.pop(),
            start_line_id=int(chunk[0].get("global_idx", 0)),
            end_line_id=int(chunk[-1].get("global_idx", 0)),
            start_line_idx=int(chunk[0].get("line_idx", 0)),
            end_line_idx=int(chunk[-1].get("line_idx", 0)),
            y_top=float(sum(tops) / len(tops)) if tops else None,
            font_max=max(fonts) if fonts else None,
            is_toc=bool(chunk[0].get("is_toc")),
            is_index=bool(chunk[0].get("is_index")),
            is_running=any(bool(item.get("is_running")) for item in chunk),
        )

    for index in range(len(usable)):
        single = _make_window([usable[index]])
        if single is not None:
            windows.append(single)
        span = usable[index : index + 3]
        if len(span) == 3:
            multi = _make_window(span)
            if multi is not None:
                windows.append(multi)

    return windows


def _bm25_index(windows: Sequence[LineWindow]) -> BM25Okapi | None:
    if BM25Okapi is None or not windows:
        return None
    corpus = [window.tokens for window in windows]
    total_tokens = sum(len(tokens) for tokens in corpus)
    if total_tokens < 5:
        return None
    return BM25Okapi(corpus)


def embed_windows(
    windows: Sequence[LineWindow],
    emb: EmbeddingsClient,
    *,
    cache_key: str | None = None,
) -> np.ndarray:
    """Return embeddings for ``windows`` texts with optional doc-level caching."""

    texts = [window.text for window in windows]
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    if cache_key:
        cache_path = _window_cache_path(cache_key, emb.settings.embeddings_cache_dir)
        if cache_path.exists():
            try:
                cached = np.load(cache_path)
                if cached.shape[0] == len(texts):
                    return cached
            except Exception:
                cache_path.unlink(missing_ok=True)

    vectors = emb.embed_batch(texts)

    if cache_key:
        cache_path = _window_cache_path(cache_key, emb.settings.embeddings_cache_dir)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache_path, vectors.astype(np.float32, copy=False))

    return vectors


def _window_cache_path(cache_key: str, cache_dir: Path) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", cache_key)
    base = Path(cache_dir)
    if not base.is_absolute():
        base = PROJECT_ROOT / base
    return base / f"{safe}.windows.npy"


def _font_rank(window: LineWindow, page_fonts: dict[int, float]) -> float:
    max_font = page_fonts.get(window.page)
    if max_font is None or not window.font_max:
        return 0.0
    return min(1.0, float(window.font_max) / max_font)


def _y_bonus(window: LineWindow, page_tops: dict[int, tuple[float, float]]) -> float:
    bounds = page_tops.get(window.page)
    if bounds is None or window.y_top is None:
        return 0.0
    top_min, top_max = bounds
    if math.isclose(top_min, top_max):
        return 0.0
    norm = (window.y_top - top_min) / max(top_max - top_min, 1e-6)
    return max(0.0, min(1.0, 1.0 - norm))


def _lexical_scores(
    header_text: str,
    windows: Sequence[LineWindow],
    bm25: BM25Okapi | None,
) -> np.ndarray:
    tokens = _tokenize(header_text)
    if not tokens:
        return np.zeros(len(windows), dtype=np.float32)
    if bm25 is not None:
        scores = bm25.get_scores(tokens)
        if scores.size:
            max_score = float(scores.max())
            if max_score > 0:
                return (scores / max_score).astype(np.float32)

    try:
        from rapidfuzz import fuzz
    except Exception:  # pragma: no cover - rapidfuzz optional
        return np.zeros(len(windows), dtype=np.float32)

    ratios = [float(fuzz.token_set_ratio(header_text, window.text) / 100.0) for window in windows]
    return np.asarray(ratios, dtype=np.float32)


def score_candidates(
    header_text: str,
    header_level: int,
    windows: Sequence[LineWindow],
    window_embeddings: np.ndarray,
    header_embedding: np.ndarray,
    *,
    weights: Sequence[float],
    thresholds: tuple[float, float],
    prefer_last: bool,
) -> list[ScoredCandidate]:
    """Return scored candidates for ``header_text`` over ``windows``."""

    if not windows:
        return []

    lexical_weight, cosine_weight, font_weight, y_weight = (
        (list(weights) + [0.0, 0.0, 0.0, 0.0])[:4]
    )

    bm25 = _bm25_index(windows)
    lexical_scores = _lexical_scores(header_text, windows, bm25)

    if window_embeddings.size == 0 or header_embedding.size == 0:
        cosine_scores = np.zeros(len(windows), dtype=np.float32)
    else:
        dots = window_embeddings @ header_embedding
        cosine_scores = np.clip(dots, -1.0, 1.0)

    page_fonts: dict[int, float] = {}
    page_tops: dict[int, tuple[float, float]] = {}
    for window in windows:
        if window.font_max:
            page_fonts[window.page] = max(page_fonts.get(window.page, 0.0), float(window.font_max))
        if window.y_top is not None:
            top_min, top_max = page_tops.get(window.page, (window.y_top, window.y_top))
            top_min = min(top_min, window.y_top)
            top_max = max(top_max, window.y_top)
            page_tops[window.page] = (top_min, top_max)

    threshold_lexical, threshold_cosine = thresholds
    candidates: list[ScoredCandidate] = []

    for index, window in enumerate(windows):
        lexical = float(lexical_scores[index])
        cosine = float(cosine_scores[index]) if index < cosine_scores.size else 0.0
        if lexical < threshold_lexical or cosine < threshold_cosine:
            continue
        if window.is_running:
            continue
        if is_probably_toc(window.text):
            continue
        font_rank = _font_rank(window, page_fonts)
        y_bonus = _y_bonus(window, page_tops)
        fused = (
            lexical_weight * lexical
            + cosine_weight * cosine
            + font_weight * font_rank
            + y_weight * y_bonus
        )
        candidates.append(
            ScoredCandidate(
                window=window,
                lexical=lexical,
                cosine=cosine,
                font_rank=font_rank,
                y_bonus=y_bonus,
                fused=fused,
            )
        )

    candidates.sort(
        key=lambda item: (
            item.fused,
            item.window.end_line_id if prefer_last else item.window.start_line_id,
        ),
        reverse=True,
    )

    return candidates


def select_anchor(candidates: Sequence[ScoredCandidate]) -> ScoredCandidate | None:
    """Return the highest-ranked candidate or ``None``."""

    if not candidates:
        return None
    return candidates[0]


def is_probably_toc(window_text: str) -> bool:
    """Return True when ``window_text`` resembles a TOC entry."""

    text = (window_text or "").strip()
    if not text:
        return False
    lower = text.lower()
    if "table of contents" in lower or lower.startswith("contents"):
        return True
    if lower.startswith("index ") or lower.startswith("index\n"):
        return True
    if TOC_PATTERN.search(text):
        return True
    return False


def export_trace(
    output_path: Path,
    *,
    anchors: list[dict],
) -> None:
    """Persist the locator diagnostics to ``output_path``."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(anchors, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = [
    "LineWindow",
    "ScoredCandidate",
    "build_line_windows",
    "embed_windows",
    "score_candidates",
    "select_anchor",
    "is_probably_toc",
    "export_trace",
]

