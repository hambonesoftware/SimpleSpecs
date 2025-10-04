from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import FigureObject, ParagraphObject, ParsedObject, TableObject

try:  # pragma: no cover - optional dependency
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    pdfplumber = None

try:  # pragma: no cover - optional dependency
    import fitz  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    fitz = None

try:  # pragma: no cover - optional dependency
    import camelot  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    camelot = None

try:  # pragma: no cover - optional dependency
    import pikepdf  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    pikepdf = None


@dataclass
class NativePdfParser:
    """Parse PDF files using locally available libraries."""

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        file_id = Path(file_path).resolve().parent.parent.name
        objects: list[ParsedObject] = []
        order_index = 0

        metadata: dict[str, Any] = {"engine": "native"}
        if pikepdf is not None:  # pragma: no branch - metadata enrichment
            try:
                with pikepdf.open(file_path) as pdf:
                    meta = getattr(pdf, "docinfo", {})
                    if meta:
                        metadata["document_metadata"] = {
                            key: str(value) for key, value in meta.items()
                        }
            except Exception:
                metadata.setdefault("warnings", []).append("pikepdf_failed")

        if pdfplumber is not None:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page_index, page in enumerate(pdf.pages):
                        text = page.extract_text() or ""
                        page_bbox = [0.0, 0.0, float(page.width or 0), float(page.height or 0)]
                        obj = ParagraphObject(
                            object_id=f"{file_id}-txt-{order_index:06d}",
                            file_id=file_id,
                            text=text.strip() or None,
                            page_index=page_index,
                            bbox=page_bbox,
                            order_index=order_index,
                            paragraph_index=order_index,
                            metadata={**metadata, "source": "pdfplumber"},
                        )
                        objects.append(obj)
                        order_index += 1
            except Exception:
                metadata.setdefault("warnings", []).append("pdfplumber_failed")

        table_entries: list[tuple[int, ParsedObject]] = []
        if camelot is not None:
            try:
                tables = camelot.read_pdf(file_path, pages="all")
                for table_idx, table in enumerate(tables):
                    page_index = int(getattr(table, "page", 1)) - 1
                    table_text = table.df.to_csv(index=False)
                    table_obj = TableObject(
                        object_id=f"{file_id}-tbl-{table_idx:06d}",
                        file_id=file_id,
                        text=table_text,
                        page_index=page_index,
                        bbox=None,
                        order_index=0,
                        n_rows=len(rows) or None,
                        n_cols=len(rows[0]) if rows and rows[0] else None,
                        markdown=table_text or None,
                        metadata={**metadata, "table_engine": "camelot"},
                    )
                    table_entries.append((page_index, table_obj))
            except Exception:
                metadata.setdefault("warnings", []).append("camelot_failed")

        image_entries: list[tuple[int, ParsedObject]] = []
        if fitz is not None:
            try:
                with fitz.open(file_path) as doc:
                    for page_index in range(doc.page_count):
                        page = doc.load_page(page_index)
                        text_dict = page.get_text("dict")
                        for block_index, block in enumerate(text_dict.get("blocks", [])):
                            if block.get("type") == 1:
                                bbox = [float(coord) for coord in block.get("bbox", (0, 0, 0, 0))]
                                image_obj = FigureObject(
                                    object_id=f"{file_id}-img-{page_index:03d}-{block_index:03d}",
                                    file_id=file_id,
                                    text=None,
                                    page_index=page_index,
                                    bbox=bbox,
                                    order_index=0,
                                    caption=None,
                                    metadata={**metadata, "source": "pymupdf"},
                                )
                                image_entries.append((page_index, image_obj))
            except Exception:
                metadata.setdefault("warnings", []).append("pymupdf_failed")

        # Merge tables and images into the ordered list by page index.
        for entries in (sorted(table_entries, key=lambda item: (item[0], item[1].object_id)), sorted(image_entries, key=lambda item: (item[0], item[1].object_id))):
            for _page_index, entry in entries:
                entry = entry.model_copy(update={"order_index": order_index})
                objects.append(entry)
                order_index += 1

        # Ensure deterministic ordering by order_index
        objects.sort(key=lambda obj: obj.order_index)
        return objects
