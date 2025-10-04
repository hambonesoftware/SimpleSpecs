"""PDF parsing using pdfplumber."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import pdfplumber


def parse_pdf(path: Path) -> list[dict[str, Any]]:
    """Parse a PDF document into normalized objects."""

    objects: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            lines: dict[tuple[int | None, float], list[dict[str, Any]]] = defaultdict(list)
            for word in words:
                key = (word.get("line_number"), round(float(word.get("top", 0.0)), 1))
                lines[key].append(word)

            for grouped in lines.values():
                grouped.sort(key=lambda w: w.get("x0", 0.0))
                content = " ".join(word.get("text", "") for word in grouped).strip()
                if not content:
                    continue
                bbox = [
                    float(min(word.get("x0", 0.0) for word in grouped)),
                    float(min(word.get("top", 0.0) for word in grouped)),
                    float(max(word.get("x1", 0.0) for word in grouped)),
                    float(max(word.get("bottom", 0.0) for word in grouped)),
                ]
                objects.append(
                    {
                        "line_id": str(uuid4()),
                        "type": "text",
                        "page": page_index,
                        "bbox": bbox,
                        "content": content,
                        "meta": None,
                    }
                )

            # Fallback to raw text if no words were detected
            if not words:
                raw_text = page.extract_text() or ""
                for line in raw_text.splitlines():
                    text = line.strip()
                    if not text:
                        continue
                    objects.append(
                        {
                            "line_id": str(uuid4()),
                            "type": "text",
                            "page": page_index,
                            "bbox": None,
                            "content": text,
                            "meta": None,
                        }
                    )

            tables = page.extract_tables() or []
            for table in tables:
                if not table:
                    continue
                content_rows = [", ".join(filter(None, row)) for row in table]
                objects.append(
                    {
                        "line_id": str(uuid4()),
                        "type": "table",
                        "page": page_index,
                        "bbox": None,
                        "content": "\n".join(content_rows),
                        "meta": {"rows": table},
                    }
                )

            for image in page.images:
                bbox = [
                    float(image.get("x0", 0.0)),
                    float(image.get("top", image.get("y0", 0.0))),
                    float(image.get("x1", 0.0)),
                    float(image.get("bottom", image.get("y1", 0.0))),
                ]
                objects.append(
                    {
                        "line_id": str(uuid4()),
                        "type": "image",
                        "page": page_index,
                        "bbox": bbox,
                        "content": "Embedded image",
                        "meta": {k: v for k, v in image.items() if k not in {"stream"}},
                    }
                )

    return objects
