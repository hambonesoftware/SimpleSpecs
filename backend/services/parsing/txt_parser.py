"""Plain text parsing."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4


def parse_txt(path: Path) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            objects.append(
                {
                    "line_id": str(uuid4()),
                    "type": "text",
                    "page": None,
                    "bbox": None,
                    "content": text,
                    "meta": None,
                }
            )
    return objects
