"""OCR helper utilities for PDF parsing."""
from __future__ import annotations

import io
import json
import logging
from typing import Any, Dict, List, Tuple

try:  # pragma: no cover - optional dependency
    import fitz  # type: ignore
except Exception:  # pragma: no cover - PyMuPDF missing
    fitz = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import pytesseract  # type: ignore
    from pytesseract import Output  # type: ignore
except Exception:  # pragma: no cover - pytesseract missing
    pytesseract = None  # type: ignore
    Output = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - pillow missing
    Image = None  # type: ignore

from .pdf_native import TextLine

logger = logging.getLogger(__name__)

_WARNED_OCR = False


def _structured_debug(enabled: bool, event: str, **data: Any) -> None:
    if not enabled:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        safe = {key: repr(value) for key, value in data.items()}
        payload = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    logger.debug("%s %s", event, payload)


def ocr_available() -> bool:
    """Return True when OCR dependencies are importable."""

    return bool(fitz and pytesseract and Image and Output)


def extract_ocr_lines(page: "fitz.Page", page_index: int, *, debug: bool = False) -> List[TextLine]:
    """Run OCR on *page* and return coarse ``TextLine`` entries."""

    global _WARNED_OCR
    if not ocr_available():  # pragma: no cover - dependency missing
        if not _WARNED_OCR:
            logger.warning("pytesseract not available; skipping OCR fallback")
            _WARNED_OCR = True
        return []

    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    data = pytesseract.image_to_data(image, output_type=Output.DICT)

    scale_x = page.rect.width / pixmap.width if pixmap.width else 1.0
    scale_y = page.rect.height / pixmap.height if pixmap.height else 1.0

    groups: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for idx, text in enumerate(data.get("text", [])):
        if not text or not text.strip():
            continue
        block = int(data["block_num"][idx])
        line = int(data["line_num"][idx])
        key = (block, line)
        entry = groups.setdefault(
            key,
            {
                "text": [],
                "x0": float("inf"),
                "y0": float("inf"),
                "x1": 0.0,
                "y1": 0.0,
                "height": 0.0,
            },
        )
        left = float(data["left"][idx])
        top = float(data["top"][idx])
        width = float(data["width"][idx])
        height = float(data["height"][idx])
        entry["text"].append(text)
        entry["x0"] = min(entry["x0"], left)
        entry["y0"] = min(entry["y0"], top)
        entry["x1"] = max(entry["x1"], left + width)
        entry["y1"] = max(entry["y1"], top + height)
        entry["height"] = max(entry["height"], height)

    lines: List[TextLine] = []
    for order, (_, entry) in enumerate(sorted(groups.items(), key=lambda item: item[1]["y0"])):
        text = " ".join(entry["text"]).strip()
        if not text:
            continue
        x0 = page.rect.x0 + entry["x0"] * scale_x
        y0 = page.rect.y0 + entry["y0"] * scale_y
        x1 = page.rect.x0 + entry["x1"] * scale_x
        y1 = page.rect.y0 + entry["y1"] * scale_y
        font_size = entry["height"] * scale_y
        rect = page.rect
        line = TextLine(
            text=text,
            bbox=(x0, y0, x1, y1),
            font_family=None,
            font_size=font_size,
            is_bold=False,
            is_caps=text.isupper(),
            page_no=page_index,
            line_idx=-1,
            column_index=None,
            span_fonts=[],
            flags=None,
            page_width=rect.width,
            page_height=rect.height,
        )
        lines.append(line)
    _structured_debug(
        debug,
        "ocr.page_result",
        page=page_index,
        lines=len(lines),
    )
    return lines
