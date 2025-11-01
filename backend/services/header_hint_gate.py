from __future__ import annotations

from typing import Iterable, Optional


class Hint:
    __slots__ = ("page", "line")

    def __init__(self, page: Optional[int], line: Optional[int]):
        self.page = page
        self.line = line


def within_page_band(candidate_page: int, hint: Hint, tol: int) -> bool:
    if hint.page is None:
        return True
    return (candidate_page >= hint.page - tol) and (candidate_page <= hint.page + tol)


def filter_candidates_by_hint(
    pairs: Iterable[tuple[int, object]], hint: Hint, tol: int
) -> list[tuple[int, object]]:
    """Filter candidates to those within the ±tol page band when a hint is available."""

    if hint.page is None:
        return list(pairs)
    lo, hi = hint.page - tol, hint.page + tol
    return [(p, obj) for (p, obj) in pairs if lo <= p <= hi]


def pick_best_in_band(
    scored: list[tuple[int, float, object]],
    hint: Hint,
    tol: int,
    strict: bool,
) -> Optional[object]:
    """Return the highest scoring candidate respecting the hint band preferences."""

    if not scored:
        return None

    if hint.page is None:
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[0][2]

    lo, hi = hint.page - tol, hint.page + tol
    in_band = [t for t in scored if lo <= t[0] <= hi]
    if in_band:
        in_band.sort(key=lambda t: t[1], reverse=True)
        return in_band[0][2]

    if strict:
        return None

    boosted = []
    for page, score, obj in scored:
        delta = abs(page - hint.page)
        bonus = 1.0 / (1.0 + float(delta))
        boosted.append((page, score + 0.05 * bonus, obj))
    boosted.sort(key=lambda t: t[1], reverse=True)
    return boosted[0][2]


__all__ = [
    "Hint",
    "filter_candidates_by_hint",
    "pick_best_in_band",
    "within_page_band",
]
