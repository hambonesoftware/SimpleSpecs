from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_path

from ..models import ParsedObject


def parse_txt(file_path: str) -> list[ParsedObject]:
    """Parse plain text files into ParsedObject entries."""

    file_id = Path(file_path).resolve().parent.parent.name
    best = from_path(file_path).best()
    if best is None:
        text = Path(file_path).read_text(encoding="utf-8")
    else:
        text = str(best)

    objects: list[ParsedObject] = []
    for index, line in enumerate(text.splitlines()):
        objects.append(
            ParsedObject(
                object_id=f"{file_id}-txt-{index:06d}",
                file_id=file_id,
                kind="text",
                text=line,
                page_index=0,
                bbox=None,
                order_index=index,
                metadata={"engine": "txt", "encoding": best.encoding if best else "utf-8"},
            )
        )
    return objects
