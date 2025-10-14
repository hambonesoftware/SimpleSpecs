from __future__ import annotations

import json
import logging
import math
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..models import FigureObject, ParagraphObject, ParsedObject, TableObject

logger = logging.getLogger(__name__)


@dataclass
class TextLine:
    """Normalized representation for a textual line emitted by PyMuPDF."""

    text: str
    bbox: tuple[float, float, float, float]
    font_family: str | None
    font_size: float | None
    is_bold: bool
    is_caps: bool
    page_no: int
    line_idx: int
    column_index: int | None = None
    span_fonts: list[str] = field(default_factory=list)
    flags: int | None = None
    page_width: float | None = None
    page_height: float | None = None

    @property
    def indent(self) -> float:
        return float(self.bbox[0])

    @property
    def baseline(self) -> float:
        return float(self.bbox[1])

    @property
    def width(self) -> float:
        return float(self.bbox[2] - self.bbox[0])


def _structured_debug(enabled: bool, event: str, **data: Any) -> None:
    if not enabled:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        safe = {key: repr(value) for key, value in data.items()}
        payload = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    logger.debug("%s %s", event, payload)


def _line_midpoint(bbox: Sequence[float]) -> float:
    return float((bbox[0] + bbox[2]) / 2.0)


def _kmeans_1d(values: Sequence[float], k: int) -> tuple[list[float], list[int], float]:
    if not values:
        return [], [], 0.0
    if k <= 1:
        mean = sum(values) / len(values)
        inertia = sum((value - mean) ** 2 for value in values)
        return [mean], [0 for _ in values], inertia
    minimum, maximum = min(values), max(values)
    if math.isclose(minimum, maximum):
        return [minimum for _ in range(k)], [0 for _ in values], 0.0
    centers = [
        minimum + (maximum - minimum) * (index + 0.5) / k for index in range(k)
    ]
    assignments = [0 for _ in values]
    for _ in range(12):
        moved = False
        for idx, value in enumerate(values):
            nearest = min(range(k), key=lambda j: abs(value - centers[j]))
            if assignments[idx] != nearest:
                assignments[idx] = nearest
                moved = True
        new_centers: list[float] = centers[:]
        for center_idx in range(k):
            cluster = [value for value, group in zip(values, assignments) if group == center_idx]
            if not cluster:
                continue
            new_centers[center_idx] = sum(cluster) / len(cluster)
        if all(math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-2) for a, b in zip(new_centers, centers)):
            centers = new_centers
            break
        centers = new_centers
        if not moved:
            break
    inertia = sum((value - centers[group]) ** 2 for value, group in zip(values, assignments))
    return centers, assignments, inertia


def _score_cluster_count(values: Sequence[float], max_k: int = 3) -> tuple[int, list[int]]:
    if len(values) < 4:
        return 1, [0 for _ in values]
    best_k = 1
    best_assignments: list[int] = [0 for _ in values]
    best_score = float("inf")
    for k in range(1, max_k + 1):
        centers, assignments, inertia = _kmeans_1d(values, k)
        if not centers:
            continue
        penalty = k * math.log(len(values) + 1)
        score = inertia + penalty
        if score < best_score - 1e-3:
            best_score = score
            best_k = k
            best_assignments = assignments
    return best_k, best_assignments


def _assign_columns(
    lines: list[dict[str, Any]], multi_column: bool, debug: bool
) -> list[int]:
    if not multi_column:
        return [0 for _ in lines]
    values = [_line_midpoint(line["bbox"]) for line in lines]
    k, assignments = _score_cluster_count(values)
    centroid_map: dict[int, list[float]] = {}
    if k > 1:
        for assignment, value in zip(assignments, values):
            centroid_map.setdefault(assignment, []).append(value)
        centroids = [
            sum(cluster) / len(cluster)
            for _, cluster in sorted(centroid_map.items(), key=lambda item: sum(item[1]) / len(item[1]))
        ]
        if centroids and (centroids[-1] - centroids[0]) < 120:
            assignments = [0 for _ in lines]
            centroid_map = {0: values}
            centroids = [sum(values) / len(values)] if values else centroids
    else:
        centroids = [values[0]] if values else []
    _structured_debug(
        debug,
        "pdf_native.columns",
        k=k,
        centroids=centroids,
    )
    if k == 1:
        return [0 for _ in lines]
    # Ensure columns ordered left-to-right
    centroids = {}
    if not centroid_map:
        for assignment, line in zip(assignments, lines):
            centroids.setdefault(assignment, []).append(_line_midpoint(line["bbox"]))
    else:
        for key, cluster_values in centroid_map.items():
            centroids[key] = cluster_values
    ordered = {
        cluster: rank
        for rank, (cluster, _) in enumerate(
            sorted(
                (
                    (cluster, sum(values) / len(values))
                    for cluster, values in centroids.items()
                ),
                key=lambda item: item[1],
            )
        )
    }
    return [ordered.get(cluster, 0) for cluster in assignments]


def _iter_page_lines(page: Any) -> Iterable[dict[str, Any]]:
    dictionary = page.get_text("dict")
    for block in dictionary.get("blocks", []):
        if block.get("type") not in (0, 1):
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(span.get("text", "") or "" for span in spans)
            if not text or not text.strip():
                continue
            yield {
                "text": text,
                "bbox": tuple(float(value) for value in line.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                "spans": spans,
            }


def extract_text_lines(
    file_path: str,
    *,
    multi_column: bool = True,
    debug: bool = False,
) -> list[TextLine]:
    """Extract text lines from *file_path* using PyMuPDF with layout heuristics."""

    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is not available")

    lines: list[TextLine] = []
    with fitz.open(file_path) as document:
        global_index = 0
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            raw_lines = list(_iter_page_lines(page))
            column_assignments = _assign_columns(raw_lines, multi_column, debug)
            combined: list[tuple[dict[str, Any], int]] = list(zip(raw_lines, column_assignments))
            combined.sort(key=lambda item: (item[1], item[0]["bbox"][1], item[0]["bbox"][0]))
            for order, (entry, column) in enumerate(combined):
                spans = entry["spans"]
                font_candidates: list[str] = []
                sizes: list[float] = []
                bold = False
                flags = 0
                for span in spans:
                    font = span.get("font")
                    if font:
                        font_candidates.append(str(font))
                    size = span.get("size")
                    if size:
                        sizes.append(float(size))
                    span_flags = int(span.get("flags", 0))
                    flags |= span_flags
                    if span_flags & 2 or (font and "bold" in str(font).lower()):
                        bold = True
                font_family = font_candidates[0] if font_candidates else None
                font_size = sum(sizes) / len(sizes) if sizes else None
                text = entry["text"].replace("\u00A0", " ").strip()
                letters = [char for char in text if char.isalpha()]
                is_caps = bool(letters) and all(char.isupper() for char in letters)
                bbox = tuple(float(value) for value in entry["bbox"])
                rect = page.rect
                line = TextLine(
                    text=text,
                    bbox=bbox,
                    font_family=font_family,
                    font_size=font_size,
                    is_bold=bold,
                    is_caps=is_caps,
                    page_no=page_index,
                    line_idx=global_index,
                    column_index=column,
                    span_fonts=font_candidates,
                    flags=flags,
                    page_width=rect.width,
                    page_height=rect.height,
                )
                lines.append(line)
                global_index += 1
            _structured_debug(
                debug,
                "pdf_native.page_summary",
                page=page_index,
                total_lines=len(raw_lines),
            )
    return lines


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
