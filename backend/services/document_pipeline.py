"""Coordinated document parsing pipeline for header extraction."""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Iterable

try:  # pragma: no cover - optional dependency
    import fitz  # type: ignore
except Exception:  # pragma: no cover - PyMuPDF missing
    fitz = None  # type: ignore

from ..config import get_settings
from ..models import HeaderItem
from .headers_detect import HeaderDetectionResult, HeaderNode, detect_headers
from .ocr import extract_ocr_lines
from .pdf_native import TextLine, extract_text_lines

logger = logging.getLogger(__name__)


def _structured_debug(enabled: bool, event: str, **data: object) -> None:
    if not enabled:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        payload = json.dumps({key: repr(value) for key, value in data.items()}, ensure_ascii=False, sort_keys=True)
    logger.debug("%s %s", event, payload)


def _augment_with_ocr(lines: list[TextLine], pdf_path: str, *, debug: bool) -> list[TextLine]:
    if fitz is None:
        return lines
    settings = get_settings()
    if not settings.PARSER_ENABLE_OCR:
        return lines
    counts = Counter(line.page_no for line in lines)
    augmented = list(lines)
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            if counts.get(page_index, 0) >= 1:
                continue
            page = document.load_page(page_index)
            ocr_lines = extract_ocr_lines(page, page_index, debug=debug)
            if not ocr_lines:
                continue
            augmented.extend(ocr_lines)
    augmented.sort(key=lambda line: (line.page_no, line.bbox[1], line.bbox[0]))
    for idx, line in enumerate(augmented):
        line.line_idx = idx
    _structured_debug(debug, "pipeline.ocr_augmented", total=len(augmented))
    return augmented


def run_header_pipeline(pdf_path: str, *, debug: bool | None = None) -> HeaderDetectionResult:
    """Execute the layout-aware pipeline for *pdf_path* and return detected headers."""

    settings = get_settings()
    debug_enabled = settings.PARSER_DEBUG if debug is None else debug
    multi_column = settings.PARSER_MULTI_COLUMN
    base_lines = extract_text_lines(pdf_path, multi_column=multi_column, debug=debug_enabled)
    lines = _augment_with_ocr(base_lines, pdf_path, debug=debug_enabled)
    result = detect_headers(
        lines,
        suppress_toc=settings.HEADERS_SUPPRESS_TOC,
        suppress_running=settings.HEADERS_SUPPRESS_RUNNING,
        debug=debug_enabled,
    )
    _structured_debug(
        debug_enabled,
        "pipeline.summary",
        pdf_path=pdf_path,
        headers=len(result.headers),
    )
    return result


__all__ = [
    "run_header_pipeline",
    "HeaderDetectionResult",
    "HeaderItem",
    "HeaderNode",
    "TextLine",
]
