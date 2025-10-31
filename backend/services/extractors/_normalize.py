from __future__ import annotations

import re

DOTS = r"[.\u2024\u2027·]"
NBSPS = "\u00A0\u2007\u2009"
SOFT_HYPH = "\u00AD"

SPACED_DOTS_RE = re.compile(r"(\d)\s*" + DOTS + r"\s*(\d)")
CONFUSABLE_ONE_RES = [
    re.compile(r"(?<=\d)\s*[Il]\s*(?=(?:\d|\b))"),
    re.compile(r"(?<=" + DOTS + r")\s*[Il]\b"),
]


def normalize_numeric_artifacts(s: str) -> str:
    s = s.replace(SOFT_HYPH, "")
    for ch in NBSPS:
        s = s.replace(ch, " ")
    s = SPACED_DOTS_RE.sub(r"\1.\2", s)
    for rx in CONFUSABLE_ONE_RES:
        s = rx.sub("1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# crude page noise scorers (operate on *raw* page text)
def score_spaced_dots_ratio(text: str) -> float:
    if not text:
        return 0.0
    spaced = len(SPACED_DOTS_RE.findall(text))
    digits = sum(ch.isdigit() for ch in text)
    if digits < 10:
        return 0.0
    return spaced / max(1, digits)


def score_confusable_one_ratio(text: str) -> float:
    if not text:
        return 0.0
    total = 0
    hits = 0
    for _ in re.finditer(r"(?:(?<=\d)|(?<=\s*\.\s*))\s*([Il])\s*(?=(?:\d|\b))", text):
        hits += 1
    for ch in text:
        if ch.isdigit():
            total += 1
    if total < 10:
        return 0.0
    return hits / max(1, total)


__all__ = [
    "normalize_numeric_artifacts",
    "score_spaced_dots_ratio",
    "score_confusable_one_ratio",
]
