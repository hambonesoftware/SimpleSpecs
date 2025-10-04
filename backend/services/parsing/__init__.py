"""Document parsing utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

from .docx_parser import parse_docx
from .pdf_parser import parse_pdf
from .txt_parser import parse_txt

_PARSERS: Dict[str, Callable[[Path], List[dict]]] = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".txt": parse_txt,
}


def parse_document(path: Path) -> list[dict]:
    """Parse a document at *path* and return a list of normalized objects."""

    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if not parser:
        raise ValueError(f"Unsupported document type: {suffix}")
    return parser(path)
