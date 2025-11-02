from __future__ import annotations

import re

DOTS = r"[.\u2024\u2027·]"
NBSPS = "\u00A0\u2007\u2009"
SOFT_HYPH = "\u00AD"

SPACED_DOTS_RE = re.compile(r"(\d)\s*" + DOTS + r"\s*(\d)")
MULTI_DOT_SEQUENCE_RE = re.compile(r"(\d(?:\.\d)*)\s*\.\s*(\d)")
CONFUSABLE_ONE_RES = [
    re.compile(r"(?<=\d)\s*[Il]\s*(?=(?:\d|\b))"),
    re.compile(r"(?<=" + DOTS + r")\s*[Il]\b"),
]


def normalize_numeric_artifacts(s: str) -> str:
    s = s.replace(SOFT_HYPH, "")
    for ch in NBSPS:
        s = s.replace(ch, " ")
    for rx in CONFUSABLE_ONE_RES:
        s = rx.sub("1", s)
    # collapse spaced dots until stable to handle multi-level labels like ``2 . 1 . 3``
    previous = None
    while s != previous:
        previous = s
        s = SPACED_DOTS_RE.sub(r"\1.\2", s)
    while True:
        collapsed = MULTI_DOT_SEQUENCE_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", s)
        if collapsed == s:
            break
        s = collapsed
    s = re.sub(r"\s+", " ", s).strip()
    return s


# crude page noise scorers (operate on *raw* page text)
def score_spaced_dots_ratio(text: str) -> float:
    if not text:
        return 0.0
    spaced = len(SPACED_DOTS_RE.findall(text))
    digits = sum(ch.isdigit() for ch in text)
    if digits < 6:
        return 0.0
    return spaced / max(1, digits)


def score_confusable_one_ratio(text: str) -> float:
    if not text:
        return 0.0
    digit_count = sum(ch.isdigit() for ch in text)
    if digit_count < 6:
        return 0.0

    spans: set[tuple[int, int]] = set()
    for rx in CONFUSABLE_ONE_RES:
        for match in rx.finditer(text):
            spans.add(match.span())

    hits = len(spans)
    return hits / max(1, digit_count)


__all__ = [
    "normalize_numeric_artifacts",
    "score_spaced_dots_ratio",
    "score_confusable_one_ratio",
]
