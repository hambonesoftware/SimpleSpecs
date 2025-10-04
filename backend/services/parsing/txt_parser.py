"""Plain text parsing."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from ...models import LINE_KIND


def parse_txt(path: Path) -> list[dict[str, Any]]:
    """Parse a UTF-8 text file into canonical parsed objects."""

    file_id = path.stem
    objects: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_index, raw_line in enumerate(fh):
            text = raw_line.rstrip("\n")
            stripped = text.strip()
            if not stripped:
                continue
            objects.append(
                {
                    "object_id": str(uuid4()),
                    "file_id": file_id,
                    "kind": LINE_KIND,
                    "text": stripped,
                    "page_index": 0,
                    "bbox": None,
                    "order_index": len(objects),
                    "line_index": line_index,
                    "is_blank": False,
                    "metadata": {"source": "txt_parser"},
                }
            )
    return objects
