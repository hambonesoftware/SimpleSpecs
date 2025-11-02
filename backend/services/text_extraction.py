from __future__ import annotations

from typing import Dict, List

from backend.config import (
    PARSER_ENGINE,
    PARSER_NOISE_CONFUSABLE_1_THRESH,
    PARSER_NOISE_SPACED_DOT_THRESH,
)

from .extractors._normalize import (
    SPACED_DOTS_RE,
    score_confusable_one_ratio,
    score_spaced_dots_ratio,
)
from .extractors.fitz_extractor import extract_lines_fitz
from .extractors.pdfium_extractor import (
    extract_lines_pdfium,
    extract_page_text_pdfium,
)


def _should_fallback_to_pdfium(pdf_path: str) -> bool:
    try:
        text = extract_page_text_pdfium(pdf_path)
    except Exception:
        return False
    spaced = score_spaced_dots_ratio(text)
    confusable = score_confusable_one_ratio(text)
    spaced_hits = len(SPACED_DOTS_RE.findall(text))
    return (
        spaced >= PARSER_NOISE_SPACED_DOT_THRESH
        or confusable >= PARSER_NOISE_CONFUSABLE_1_THRESH
        or spaced_hits >= 50
    )


def extract_lines(pdf_path: str) -> List[Dict[str, object]]:
    engine = (PARSER_ENGINE or "auto").lower()
    if engine == "fitz":
        return extract_lines_fitz(pdf_path)
    if engine == "pdfium":
        return extract_lines_pdfium(pdf_path)

    try:
        lines = extract_lines_fitz(pdf_path)
    except Exception:
        return extract_lines_pdfium(pdf_path)

    try:
        if _should_fallback_to_pdfium(pdf_path):
            return extract_lines_pdfium(pdf_path)
    except Exception:
        pass
    return lines


__all__ = ["extract_lines"]
