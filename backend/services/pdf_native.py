from __future__ import annotations

import json
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import FigureObject, ParagraphObject, ParsedObject, TableObject

logger = logging.getLogger(__name__)


def _hydrate_pymupdf_metadata() -> None:
    """Ensure SWIG-generated PyMuPDF types expose a ``__module__`` attribute."""

    try:  # pragma: no cover - optional dependency
        import gc
        import pymupdf.mupdf as mupdf  # type: ignore
    except Exception:  # pragma: no cover - PyMuPDF not importable
        return

    pending = {"SwigPyPacked", "SwigPyObject", "swigvarlink"}
    for candidate in gc.get_objects():  # pragma: no branch - bounded set
        if not isinstance(candidate, type):
            continue
        name = getattr(candidate, "__name__", None)
        if name not in pending:
            continue
        if getattr(candidate, "__module__", None) != "pymupdf.mupdf":
            try:
                candidate.__module__ = "pymupdf.mupdf"
            except Exception:  # pragma: no cover - readonly type metadata
                continue
        pending.remove(name)
        if not pending:
            break


try:  # pragma: no cover - optional dependency
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    pdfplumber = None

try:  # pragma: no cover - optional dependency
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="builtin type .* has no __module__ attribute",
            category=DeprecationWarning,
        )
        import fitz  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    fitz = None
else:  # pragma: no cover - executed only when PyMuPDF is importable
    _hydrate_pymupdf_metadata()

try:  # pragma: no cover - optional dependency
    import camelot  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    camelot = None

try:  # pragma: no cover - optional dependency
    import pikepdf  # type: ignore
except Exception:  # pragma: no cover - dependency missing
    pikepdf = None


def _log_event(event: str, **data: Any) -> None:
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        safe = {key: str(value) for key, value in data.items()}
        payload = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    logger.debug("%s %s", event, payload)


def _column_metadata(page: Any) -> dict[str, float | int]:
    if not hasattr(page, "extract_words"):
        return {"columns": 1, "gap": 0.0}
    try:
        words = page.extract_words() or []
    except Exception:
        return {"columns": 1, "gap": 0.0}
    x_values = sorted(
        float(word.get("x0", 0.0)) for word in words if isinstance(word, dict) and "x0" in word
    )
    if len(x_values) < 4:
        return {"columns": 1, "gap": 0.0}
    mid = len(x_values) // 2
    left = x_values[:mid]
    right = x_values[mid:]
    if not left or not right:
        return {"columns": 1, "gap": 0.0}
    gap = min(right) - max(left)
    columns = 2 if gap > 70 else 1
    return {"columns": columns, "gap": round(gap, 2)}


@dataclass
class NativePdfParser:
    """Parse PDF files using locally available libraries."""

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        file_id = Path(file_path).resolve().parent.parent.name
        objects: list[ParsedObject] = []
        order_index = 0

        _log_event("native_pdf.start", file_id=file_id, path=str(file_path))
        metadata: dict[str, Any] = {"engine": "native"}
        if pikepdf is not None:  # pragma: no branch - metadata enrichment
            try:
                with pikepdf.open(file_path) as pdf:
                    meta = getattr(pdf, "docinfo", {})
                    if meta:
                        metadata["document_metadata"] = {
                            key: str(value) for key, value in meta.items()
                        }
                        _log_event(
                            "native_pdf.metadata",
                            file_id=file_id,
                            keys=sorted(metadata["document_metadata"].keys()),
                        )
            except Exception:
                metadata.setdefault("warnings", []).append("pikepdf_failed")
                _log_event("native_pdf.metadata_error", file_id=file_id, source="pikepdf")

        text_objects: list[ParagraphObject] = []
        pdfplumber_failed = False
        if pdfplumber is not None:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page_index, page in enumerate(pdf.pages):
                        page_start = time.perf_counter()
                        text = page.extract_text() or ""
                        elapsed = (time.perf_counter() - page_start) * 1000
                        column_info = _column_metadata(page)
                        page_bbox = [0.0, 0.0, float(page.width or 0), float(page.height or 0)]
                        text_objects.append(
                            ParagraphObject(
                                object_id=f"{file_id}-txt-{len(text_objects):06d}",
                                file_id=file_id,
                                text=text.strip() or None,
                                page_index=page_index,
                                bbox=page_bbox,
                                order_index=0,
                                paragraph_index=len(text_objects),
                                metadata={**metadata, "source": "pdfplumber"},
                            )
                        )
                        _log_event(
                            "native_pdf.page",
                            file_id=file_id,
                            page_index=page_index,
                            engine="pdfplumber",
                            elapsed_ms=round(elapsed, 2),
                            text_length=len(text.strip()),
                            columns=column_info["columns"],
                            column_gap=column_info["gap"],
                        )
            except Exception:
                pdfplumber_failed = True
                metadata.setdefault("warnings", []).append("pdfplumber_failed")
                _log_event("native_pdf.page_error", file_id=file_id, engine="pdfplumber")

        doc = None
        if fitz is not None:
            try:
                doc = fitz.open(file_path)
            except Exception:
                metadata.setdefault("warnings", []).append("pymupdf_failed")
                doc = None
                _log_event("native_pdf.open_error", file_id=file_id, engine="pymupdf")

        if not text_objects and doc is not None:
            try:
                for page_index in range(doc.page_count):
                    page_start = time.perf_counter()
                    page = doc.load_page(page_index)
                    text = page.get_text("text") or ""
                    rect = page.rect or fitz.Rect(0, 0, 0, 0)
                    text_objects.append(
                        ParagraphObject(
                            object_id=f"{file_id}-txt-{len(text_objects):06d}",
                            file_id=file_id,
                            text=text.strip() or None,
                            page_index=page_index,
                            bbox=[float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                            order_index=0,
                            paragraph_index=len(text_objects),
                            metadata={**metadata, "source": "pymupdf"},
                        )
                    )
                    elapsed = (time.perf_counter() - page_start) * 1000
                    _log_event(
                        "native_pdf.page",
                        file_id=file_id,
                        page_index=page_index,
                        engine="pymupdf",
                        elapsed_ms=round(elapsed, 2),
                        text_length=len(text.strip()),
                        columns=1,
                        column_gap=0.0,
                    )
            except Exception:
                metadata.setdefault("warnings", []).append("pymupdf_text_failed")
                _log_event("native_pdf.page_error", file_id=file_id, engine="pymupdf_text")

        if not text_objects:
            if pdfplumber_failed:
                metadata.setdefault("warnings", []).append("text_extraction_failed")
                _log_event("native_pdf.text_missing", file_id=file_id)

        for obj in text_objects:
            updated = obj.model_copy(update={"order_index": order_index, "paragraph_index": order_index})
            objects.append(updated)
            order_index += 1

        table_entries: list[tuple[int, ParsedObject]] = []
        if camelot is not None:
            try:
                camelot_start = time.perf_counter()
                tables = camelot.read_pdf(file_path, pages="all")
                for table_idx, table in enumerate(tables):
                    page_index = int(getattr(table, "page", 1)) - 1
                    table_text = table.df.to_csv(index=False)
                    rows = table.df.values.tolist()
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
                elapsed = (time.perf_counter() - camelot_start) * 1000
                _log_event(
                    "native_pdf.tables",
                    file_id=file_id,
                    engine="camelot",
                    count=len(table_entries),
                    elapsed_ms=round(elapsed, 2),
                )
            except Exception:
                metadata.setdefault("warnings", []).append("camelot_failed")
                _log_event("native_pdf.table_error", file_id=file_id, engine="camelot")

        image_entries: list[tuple[int, ParsedObject]] = []
        if doc is not None:
            try:
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
                    image_count = sum(
                        1 for block in text_dict.get("blocks", []) if block.get("type") == 1
                    )
                    _log_event(
                        "native_pdf.images",
                        file_id=file_id,
                        page_index=page_index,
                        count=image_count,
                    )
            except Exception:
                metadata.setdefault("warnings", []).append("pymupdf_image_failed")
                _log_event("native_pdf.image_error", file_id=file_id, engine="pymupdf")
        elif fitz is not None:
            try:
                with fitz.open(file_path) as fallback_doc:
                    for page_index in range(fallback_doc.page_count):
                        page = fallback_doc.load_page(page_index)
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
                        image_count = sum(
                            1 for block in text_dict.get("blocks", []) if block.get("type") == 1
                        )
                        _log_event(
                            "native_pdf.images",
                            file_id=file_id,
                            page_index=page_index,
                            count=image_count,
                            mode="fallback",
                        )
            except Exception:
                metadata.setdefault("warnings", []).append("pymupdf_failed")
                _log_event("native_pdf.image_error", file_id=file_id, engine="pymupdf_fallback")

        if doc is not None:
            doc.close()

        # Merge tables and images into the ordered list by page index.
        for entries in (sorted(table_entries, key=lambda item: (item[0], item[1].object_id)), sorted(image_entries, key=lambda item: (item[0], item[1].object_id))):
            for _page_index, entry in entries:
                entry = entry.model_copy(update={"order_index": order_index})
                objects.append(entry)
                order_index += 1
        
        # Ensure deterministic ordering by order_index
        objects.sort(key=lambda obj: obj.order_index)
        _log_event("native_pdf.summary", file_id=file_id, object_count=len(objects))
        return objects
