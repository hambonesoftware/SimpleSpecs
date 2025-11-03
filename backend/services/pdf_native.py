"""Native PDF parsing service with multi-column and suppression heuristics."""

from __future__ import annotations

import io
import hashlib
import tempfile

import logging
import re
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz  # type: ignore
import pdfplumber  # type: ignore

try:  # pragma: no cover - optional dependency
    import camelot  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    camelot = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from ..config import Settings
from ..utils.trace import HeaderTracer
from .text_extraction import extract_lines

warnings.filterwarnings("ignore", category=DeprecationWarning, module="pytesseract")

LOGGER = logging.getLogger(__name__)


def _coerce_optional_float(value: Any) -> float | None:
    """Return ``value`` as a float when possible, otherwise ``None``."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ParsedBlock:
    """Discrete text block extracted from a PDF page."""

    text: str
    bbox: tuple[float, float, float, float]
    font: str | None = None
    font_size: float | None = None
    source: str = "pymupdf"


@dataclass
class ParsedTable:
    """Marker describing a detected table region."""

    page_number: int
    bbox: tuple[float, float, float, float]
    flavor: str | None = None
    accuracy: float | None = None


@dataclass
class ParsedPage:
    """Parsed representation of a single PDF page."""

    page_number: int
    width: float
    height: float
    blocks: list[ParsedBlock] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    is_toc: bool = False


@dataclass
class ParseResult:
    """Aggregate parse result for an entire document."""

    pages: list[ParsedPage]
    has_ocr: bool = False
    used_mineru: bool = False

    def to_dict(self) -> dict:
        """Convert the parse result into a JSON-serialisable dictionary."""

        return {
            "pages": [
                {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                    "blocks": [
                        {
                            "text": block.text,
                            "bbox": block.bbox,
                            "font": block.font,
                            "font_size": block.font_size,
                            "source": block.source,
                        }
                        for block in page.blocks
                    ],
                    "tables": [
                        {
                            "bbox": table.bbox,
                            "flavor": table.flavor,
                            "accuracy": table.accuracy,
                        }
                        for table in page.tables
                    ],
                    "is_toc": page.is_toc,
                }
                for page in self.pages
            ],
            "has_ocr": self.has_ocr,
            "used_mineru": self.used_mineru,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParseResult":
        """Rehydrate a :class:`ParseResult` instance from a cached payload."""

        pages_payload = payload.get("pages") or []
        pages: list[ParsedPage] = []
        for entry in pages_payload:
            if not isinstance(entry, Mapping):
                continue
            blocks_payload = entry.get("blocks") or []
            blocks: list[ParsedBlock] = []
            for block_entry in blocks_payload:
                if not isinstance(block_entry, Mapping):
                    continue
                bbox_values = block_entry.get("bbox", (0.0, 0.0, 0.0, 0.0))
                bbox_tuple = (0.0, 0.0, 0.0, 0.0)
                if isinstance(bbox_values, Iterable) and not isinstance(
                    bbox_values, (str, bytes)
                ):
                    try:
                        coords = [float(value) for value in bbox_values]
                    except (TypeError, ValueError):
                        coords = []
                    if len(coords) == 4:
                        bbox_tuple = tuple(coords)
                blocks.append(
                    ParsedBlock(
                        text=str(block_entry.get("text", "")),
                        bbox=bbox_tuple,  # type: ignore[arg-type]
                        font=block_entry.get("font"),
                        font_size=_coerce_optional_float(block_entry.get("font_size")),
                        source=str(block_entry.get("source", "")),
                    )
                )

            tables_payload = entry.get("tables") or []
            tables: list[ParsedTable] = []
            for table_entry in tables_payload:
                if not isinstance(table_entry, Mapping):
                    continue
                bbox_values = table_entry.get("bbox", (0.0, 0.0, 0.0, 0.0))
                bbox_tuple = (0.0, 0.0, 0.0, 0.0)
                if isinstance(bbox_values, Iterable) and not isinstance(
                    bbox_values, (str, bytes)
                ):
                    try:
                        coords = [float(value) for value in bbox_values]
                    except (TypeError, ValueError):
                        coords = []
                    if len(coords) == 4:
                        bbox_tuple = tuple(coords)
                tables.append(
                    ParsedTable(
                        page_number=int(entry.get("page_number", 0)),
                        bbox=bbox_tuple,  # type: ignore[arg-type]
                        flavor=(
                            str(table_entry.get("flavor"))
                            if table_entry.get("flavor") is not None
                            else None
                        ),
                        accuracy=_coerce_optional_float(table_entry.get("accuracy")),
                    )
                )

            pages.append(
                ParsedPage(
                    page_number=int(entry.get("page_number", 0)),
                    width=float(entry.get("width", 0.0)),
                    height=float(entry.get("height", 0.0)),
                    blocks=blocks,
                    tables=tables,
                    is_toc=bool(entry.get("is_toc", False)),
                )
            )

        return cls(
            pages=pages,
            has_ocr=bool(payload.get("has_ocr", False)),
            used_mineru=bool(payload.get("used_mineru", False)),
        )


class ParseError(RuntimeError):
    """Raised when a document cannot be parsed."""


def parse_pdf_to_lines(file_path: str | Path) -> list[dict]:
    """Return normalised line entries extracted from ``file_path``."""

    return extract_lines(str(file_path))


def parse_pdf(document_path: Path, *, settings: Settings) -> ParseResult:
    """Parse a PDF file using PyMuPDF with heuristics and fallbacks."""

    if not document_path.exists():
        raise ParseError(f"Document not found: {document_path}")

    pages: list[ParsedPage] = []
    used_ocr = False
    used_mineru = False

    with fitz.open(document_path) as pdf_document, pdfplumber.open(
        document_path
    ) as plumber_document:
        plumber_pages = list(plumber_document.pages)
        for index, page in enumerate(pdf_document):
            plumber_page = plumber_pages[index] if index < len(plumber_pages) else None
            parsed_page, page_used_ocr = _parse_page(
                page=page,
                plumber_page=plumber_page,
                settings=settings,
            )
            used_ocr = used_ocr or page_used_ocr
            pages.append(parsed_page)

    if settings.headers_suppress_running:
        _suppress_running_headers(pages)

    if settings.headers_suppress_toc:
        for page in pages:
            page.is_toc = _is_toc_page(page)
            if page.is_toc:
                page.blocks = []

    tables = _detect_tables(document_path, len(pages))
    for table in tables:
        if 0 <= table.page_number < len(pages):
            pages[table.page_number].tables.append(table)

    if not any(page.blocks for page in pages) and settings.mineru_fallback:
        mineru_pages = _run_mineru_fallback(document_path)
        if mineru_pages:
            pages = mineru_pages
            used_mineru = True
        else:  # pragma: no cover - optional path
            LOGGER.warning(
                "MinerU fallback enabled but produced no output for %s", document_path
            )

    return ParseResult(pages=pages, has_ocr=used_ocr, used_mineru=used_mineru)


def _parse_page(
    *, page: fitz.Page, plumber_page, settings: Settings
) -> tuple[ParsedPage, bool]:
    rect = page.rect
    blocks = _extract_pymupdf_blocks(page)

    if not blocks and plumber_page is not None:
        blocks = _extract_pdfplumber_blocks(plumber_page)

    used_ocr = False
    if not blocks and settings.parser_enable_ocr:
        ocr_blocks = _extract_ocr_blocks(page)
        if ocr_blocks:
            blocks = ocr_blocks
            used_ocr = True

    if settings.parser_multi_column:
        blocks = _order_blocks_by_columns(blocks, rect.width)
    else:
        blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

    parsed_page = ParsedPage(
        page_number=page.number,
        width=float(rect.width),
        height=float(rect.height),
        blocks=blocks,
    )
    return parsed_page, used_ocr


def _extract_pymupdf_blocks(page: fitz.Page) -> list[ParsedBlock]:
    """Extract text blocks from a PyMuPDF page."""

    text_dict = page.get_text("dict")
    blocks: list[ParsedBlock] = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        spans = []
        for line in block.get("lines", []):
            spans.extend(line.get("spans", []))
        if not spans:
            continue
        collected_text: list[str] = []
        font: str | None = None
        font_size: float | None = None
        for span in spans:
            text = span.get("text", "").strip()
            if not text:
                continue
            collected_text.append(text)
            if font is None:
                font = span.get("font")
            if font_size is None:
                font_size = float(span.get("size", 0))
        combined = " ".join(collected_text).strip()
        if not combined:
            continue
        bbox = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
        blocks.append(
            ParsedBlock(
                text=combined,
                bbox=bbox,  # type: ignore[arg-type]
                font=font,
                font_size=font_size,
                source="pymupdf",
            )
        )
    return blocks


def _extract_pdfplumber_blocks(plumber_page) -> list[ParsedBlock]:
    """Fallback block extraction via pdfplumber."""

    try:
        text = plumber_page.extract_text()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        LOGGER.debug("pdfplumber failed to extract text", exc_info=True)
        text = None
    if not text:
        return []
    bbox = (
        0.0,
        0.0,
        float(getattr(plumber_page, "width", 0.0)),
        float(getattr(plumber_page, "height", 0.0)),
    )
    return [ParsedBlock(text=text.strip(), bbox=bbox, source="pdfplumber")]


def _extract_ocr_blocks(
    page: fitz.Page,
) -> list[ParsedBlock]:  # pragma: no cover - depends on tesseract
    if pytesseract is None or Image is None:
        LOGGER.warning("OCR requested but pytesseract/Pillow not available")
        return []
    pixmap = page.get_pixmap()
    mode = "RGBA" if pixmap.alpha else "RGB"
    image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    text = pytesseract.image_to_string(Image.open(buffer))
    if not text.strip():
        return []
    rect = page.rect
    return [
        ParsedBlock(
            text=text.strip(),
            bbox=(0.0, 0.0, float(rect.width), float(rect.height)),
            source="ocr",
        )
    ]


def _order_blocks_by_columns(
    blocks: list[ParsedBlock], page_width: float
) -> list[ParsedBlock]:
    if not blocks:
        return []
    tolerance = max(page_width * 0.02, 5.0)
    columns: list[tuple[float, list[ParsedBlock]]] = []
    for block in sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        placed = False
        for index, (col_x, col_blocks) in enumerate(columns):
            if abs(block.bbox[0] - col_x) <= tolerance:
                col_blocks.append(block)
                columns[index] = (min(col_x, block.bbox[0]), col_blocks)
                placed = True
                break
        if not placed:
            columns.append((block.bbox[0], [block]))
    columns.sort(key=lambda entry: entry[0])
    ordered: list[ParsedBlock] = []
    for _, col_blocks in columns:
        ordered.extend(sorted(col_blocks, key=lambda b: (b.bbox[1], b.bbox[0])))
    return ordered


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _suppress_running_headers(pages: list[ParsedPage]) -> None:
    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()
    for page in pages:
        if not page.blocks:
            continue
        top_threshold = page.height * 0.12
        bottom_threshold = page.height * 0.88
        for block in page.blocks:
            norm = _normalise_text(block.text)
            if not norm or len(norm) < 3:
                continue
            if block.bbox[1] <= top_threshold:
                header_counter[norm] += 1
            elif block.bbox[3] >= bottom_threshold:
                footer_counter[norm] += 1
    header_texts = {text for text, count in header_counter.items() if count > 1}
    footer_texts = {text for text, count in footer_counter.items() if count > 1}
    if not header_texts and not footer_texts:
        return
    for page in pages:
        filtered: list[ParsedBlock] = []
        for block in page.blocks:
            norm = _normalise_text(block.text)
            if norm in header_texts or norm in footer_texts:
                continue
            filtered.append(block)
        page.blocks = filtered


def _is_toc_page(page: ParsedPage) -> bool:
    if page.page_number > 4 or not page.blocks:
        return False
    text_blob = " ".join(block.text.lower() for block in page.blocks)
    if "table of contents" in text_blob or text_blob.strip().startswith("contents"):
        return True
    dotted_entries = sum(
        1 for block in page.blocks if re.search(r"\.{2,}\s*\d+$", block.text)
    )
    return dotted_entries >= max(4, len(page.blocks) // 2)


_INDEX_ENTRY_RE = re.compile(
    r"^[A-Z][A-Za-z0-9\s'’\-(),/]+\s+\.{2,}\s*\d+(?:\s*,\s*\d+)*$"
)


def _is_toc_like(lines: list[str], page_number: int) -> bool:
    if not lines:
        return False

    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return False

    lowered = [line.lower() for line in cleaned]
    if any(
        entry.startswith("table of contents") or entry == "contents"
        for entry in lowered
    ):
        return True

    dotted_entries = sum(
        1 for line in cleaned if re.search(r"\.{2,}\s*\d+$", line)
    )
    dot_only = sum(1 for line in cleaned if re.fullmatch(r"\.{3,}", line))
    threshold = max(4, len(cleaned) // 2)

    if dotted_entries >= threshold:
        return True
    if dot_only >= 12:
        return True
    if dot_only >= 6 and dotted_entries >= 1:
        return True

    return False


def _is_index_like(lines: list[str]) -> bool:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return False
    first = cleaned[0].lower()
    if first in {"index", "glossary"}:
        return True
    hits = sum(1 for line in cleaned if _INDEX_ENTRY_RE.match(line))
    return hits >= max(6, len(cleaned) // 2)


def collect_line_metrics(
    document_bytes: bytes,
    metadata: dict | None,
    *,
    suppress_toc: bool = True,
    suppress_running: bool = True,
    tracer: HeaderTracer | None = None,
) -> tuple[list[dict], set[int], str]:
    """Return flattened line metrics for the provided PDF bytes."""

    if tracer:
        tracer.log_call(f"{__name__}.collect_line_metrics")

    doc_hash = hashlib.sha256(document_bytes).hexdigest()
    excluded_pages: set[int] = set()
    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()
    page_heights: dict[int, float] = {}
    try:
        with fitz.open(stream=document_bytes, filetype="pdf") as pdf_document:
            for page in pdf_document:
                page_heights[int(page.number) + 1] = float(page.rect.height)
    except Exception:
        page_heights = {}

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file.write(document_bytes)
            temp_file.flush()
            temp_path = Path(temp_file.name)
        extracted_lines = extract_lines(str(temp_path))
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    all_lines: list[dict] = []
    page_texts: dict[int, list[str]] = defaultdict(list)
    page_entries: dict[int, list[dict]] = defaultdict(list)
    line_norms: dict[int, str] = {}
    page_line_counters: dict[int, int] = defaultdict(int)

    sample_budget = 10
    for entry in sorted(extracted_lines, key=lambda item: int(item.get("global_idx", 0))):
        text = str(entry.get("text", ""))
        if not text.strip():
            continue
        page_number = int(entry.get("page", 0) or 0)
        global_idx = int(entry.get("global_idx", len(all_lines)))
        line_idx = page_line_counters[page_number]
        page_line_counters[page_number] += 1

        bbox = entry.get("bbox")
        left = top = right = bottom = None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            left, top, right, bottom = (float(value) for value in bbox)

        if tracer and sample_budget > 0:
            tracer.ev(
                "pre_normalize_sample",
                page=page_number,
                line_idx=line_idx,
                text=text,
            )
            sample_budget -= 1

        normalised = _normalise_text(text)
        if tracer and line_idx < 5 and normalised:
            tracer.ev(
                "normalized_line",
                page=page_number,
                line_idx=line_idx,
                raw=text,
                normalised=normalised,
            )

        height = page_heights.get(page_number)
        if normalised and height is not None and top is not None and bottom is not None:
            top_threshold = height * 0.18
            bottom_threshold = height * 0.85
            if top <= top_threshold:
                header_counter[normalised] += 1
            elif bottom >= bottom_threshold:
                footer_counter[normalised] += 1

        line_norms[global_idx] = normalised
        page_texts[page_number].append(text)
        payload = {
            "global_idx": global_idx,
            "page": page_number,
            "line_idx": line_idx,
            "text": text,
            "bbox": bbox,
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom,
            "is_toc": False,
            "is_index": False,
            "is_running": False,
        }
        page_entries[page_number].append(payload)
        all_lines.append(payload)

    running_markers: set[str] = set()
    if suppress_running:
        running_markers = {
            text for text, count in header_counter.items() if count > 1
        } | {text for text, count in footer_counter.items() if count > 1}
        if tracer and running_markers:
            for text in sorted(running_markers):
                tracer.ev(
                    "running_header_filtered",
                    text=text,
                    header_hits=header_counter.get(text, 0),
                    footer_hits=footer_counter.get(text, 0),
                )

    if suppress_running and running_markers:
        for payload in all_lines:
            norm = line_norms.get(int(payload.get("global_idx", -1)))
            if norm and norm in running_markers:
                payload["is_running"] = True

    if suppress_toc:
        for page_number, texts in page_texts.items():
            is_toc_page = _is_toc_like(texts, page_number)
            is_index_page = _is_index_like(texts)
            if is_toc_page or is_index_page:
                excluded_pages.add(page_number)
                if tracer:
                    tracer.ev(
                        "toc_detected",
                        page=page_number,
                        reason="index" if is_index_page else "toc",
                        sample=texts[:6],
                    )
            for payload in page_entries.get(page_number, []):
                payload["is_toc"] = is_toc_page
                payload["is_index"] = is_index_page

    if tracer:
        tracer.ev(
            "doc_stats",
            pages=len(page_texts),
            lines=len(all_lines),
            bytes=len(document_bytes),
            excluded_pages=sorted(excluded_pages),
        )

    return all_lines, excluded_pages, doc_hash


def _detect_tables(
    document_path: Path, page_count: int
) -> list[ParsedTable]:  # pragma: no cover - heavy dependency
    if camelot is None or page_count == 0:
        return []
    try:
        tables = camelot.read_pdf(
            str(document_path), pages=f"1-{page_count}", flavor="stream"
        )
    except Exception:
        LOGGER.debug("Camelot table detection failed", exc_info=True)
        return []
    markers: list[ParsedTable] = []
    for table in tables:
        page_number = getattr(table, "page", 1) - 1
        bbox = getattr(table, "_bbox", None)
        if not bbox:
            continue
        try:
            parsed_bbox = tuple(float(value) for value in bbox)
        except Exception:
            continue
        markers.append(
            ParsedTable(
                page_number=page_number,
                bbox=parsed_bbox,  # type: ignore[arg-type]
                flavor=getattr(table, "flavor", None),
                accuracy=getattr(table, "accuracy", None),
            )
        )
    return markers


def _run_mineru_fallback(
    document_path: Path,
) -> list[ParsedPage]:  # pragma: no cover - placeholder
    try:
        from mineru import parse as mineru_parse  # type: ignore
    except Exception:
        LOGGER.info("MinerU fallback requested but package unavailable")
        return []
    try:
        mineru_result = mineru_parse(str(document_path))
    except Exception:
        LOGGER.warning("MinerU fallback failed for %%s", document_path, exc_info=True)
        return []
    pages: list[ParsedPage] = []
    for index, page in enumerate(mineru_result.get("pages", [])):
        text = page.get("text")
        if not text:
            continue
        pages.append(
            ParsedPage(
                page_number=index,
                width=float(page.get("width", 0.0)),
                height=float(page.get("height", 0.0)),
                blocks=[
                    ParsedBlock(
                        text=str(text),
                        bbox=(
                            0.0,
                            0.0,
                            float(page.get("width", 0.0)),
                            float(page.get("height", 0.0)),
                        ),
                        source="mineru",
                    )
                ],
            )
        )
    return pages
