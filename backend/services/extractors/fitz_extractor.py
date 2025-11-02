from __future__ import annotations

from typing import Dict, List

import fitz

from backend.config import PARSER_KEEP_BBOX, PARSER_LINE_Y_TOLERANCE

from ._normalize import normalize_numeric_artifacts


def _group_words_into_lines(words: list) -> List[Dict[str, object]]:
    lines: List[Dict[str, object]] = []
    if not words:
        return lines

    words.sort(key=lambda w: (w[1], w[0]))
    current_y = None
    buffer: list = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = " ".join(entry[4] for entry in buffer)
        if not text.strip():
            buffer = []
            return
        x0 = min(entry[0] for entry in buffer)
        y0 = min(entry[1] for entry in buffer)
        x1 = max(entry[2] for entry in buffer)
        y1 = max(entry[3] for entry in buffer)
        lines.append({"_text": text, "_bbox": (x0, y0, x1, y1)})
        buffer = []

    for word in words:
        y0 = word[1]
        if current_y is None:
            current_y = y0
            buffer = [word]
            continue
        if abs(y0 - current_y) <= PARSER_LINE_Y_TOLERANCE:
            buffer.append(word)
        else:
            flush()
            current_y = y0
            buffer = [word]
    flush()
    return lines


def extract_lines_fitz(pdf_path: str) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    global_idx = 0
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            words = page.get_text("words")
            grouped = _group_words_into_lines(words)
            for record in grouped:
                raw_text = record["_text"]
                text = normalize_numeric_artifacts(raw_text)
                bbox = record["_bbox"] if PARSER_KEEP_BBOX else None
                output.append(
                    {
                        "text": text,
                        "page": page_number,
                        "global_idx": global_idx,
                        "bbox": bbox,
                    }
                )
                global_idx += 1
    return output


__all__ = ["extract_lines_fitz"]
