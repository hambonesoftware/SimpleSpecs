from __future__ import annotations

from typing import Dict, List

import fitz

from backend.config import PARSER_KEEP_BBOX
from ._normalize import normalize_numeric_artifacts


def _lines_from_rawdict(raw: dict) -> List[Dict[str, object]]:
    lines: List[Dict[str, object]] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            size_max = max(float(span.get("size", 0.0)) for span in spans)
            bold = any((int(span.get("flags", 0)) & 2) != 0 for span in spans)
            x0 = min(span.get("bbox", [0.0, 0.0, 0.0, 0.0])[0] for span in spans)
            y0 = min(span.get("bbox", [0.0, 0.0, 0.0, 0.0])[1] for span in spans)
            x1 = max(span.get("bbox", [0.0, 0.0, 0.0, 0.0])[2] for span in spans)
            y1 = max(span.get("bbox", [0.0, 0.0, 0.0, 0.0])[3] for span in spans)
            lines.append(
                {
                    "_text": text,
                    "_bbox": (x0, y0, x1, y1),
                    "_size": size_max,
                    "_bold": bold,
                }
            )
    lines.sort(key=lambda entry: (entry["_bbox"][1], entry["_bbox"][0]))
    return lines


def extract_lines_fitz(pdf_path: str) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    global_idx = 0
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            raw = page.get_text("rawdict")
            lines = _lines_from_rawdict(raw)
            for entry in lines:
                raw_text = entry["_text"]
                text = normalize_numeric_artifacts(raw_text)
                bbox = entry["_bbox"] if PARSER_KEEP_BBOX else None
                output.append(
                    {
                        "text": text,
                        "page": page_number,
                        "global_idx": global_idx,
                        "bbox": bbox,
                        "font_size": entry.get("_size"),
                        "bold": bool(entry.get("_bold")),
                    }
                )
                global_idx += 1
    return output


__all__ = ["extract_lines_fitz"]
