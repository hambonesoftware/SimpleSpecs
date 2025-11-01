from backend.services.header_hint_gate import (
    Hint,
    filter_candidates_by_hint,
    pick_best_in_band,
)


def test_filter_in_band() -> None:
    pairs = [(8, "a"), (9, "b"), (11, "c"), (15, "d")]
    hint = Hint(page=10, line=None)
    out = filter_candidates_by_hint(pairs, hint, tol=2)
    assert [p for p, _ in out] == [8, 9, 11]


def test_pick_best_strict_in_band() -> None:
    scored = [(8, 0.7, "A"), (12, 0.9, "B"), (11, 0.6, "C")]
    hint = Hint(page=10, line=None)
    chosen = pick_best_in_band(scored, hint, tol=2, strict=True)
    assert chosen in ("A", "B", "C")


def test_pick_best_soft_prefers_band_but_fallback() -> None:
    scored = [(14, 0.81, "X"), (5, 0.79, "Y")]
    hint = Hint(page=10, line=None)
    chosen = pick_best_in_band(scored, hint, tol=2, strict=False)
    assert chosen in ("X", "Y")
