"""Native PDF parsing service with multi-column and suppression heuristics."""

from __future__ import annotations

import io
import hashlib

import logging
import re
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

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

warnings.filterwarnings("ignore", category=DeprecationWarning, module="pytesseract")

LOGGER = logging.getLogger(__name__)


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


class ParseError(RuntimeError):
    """Raised when a document cannot be parsed."""


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
    if page_number > 4 or not lines:
        return False
    blob = " ".join(line.lower() for line in lines)
    if "table of contents" in blob or blob.strip().startswith("contents"):
        return True
    dotted_entries = sum(1 for line in lines if re.search(r"\.{2,}\s*\d+$", line))
    return dotted_entries >= max(4, len(lines) // 2)


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

    doc_hash = hashlib.sha256(document_bytes).hexdigest()
    excluded_pages: set[int] = set()
    pages: list[dict] = []
    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()

    with fitz.open(stream=document_bytes, filetype="pdf") as pdf_document:
        sample_budget = 10
        for page in pdf_document:
            page_number = int(page.number)
            text_dict = page.get_text("dict") or {}
            raw_blocks = text_dict.get("blocks") or []
            page_lines: list[dict] = []

            for block in raw_blocks:
                if block.get("type", 0) != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(span.get("text", "") for span in spans).replace("\r", "")
                    if not text or not text.strip():
                        continue
                    bbox = line.get("bbox") or block.get("bbox")
                    if not bbox:
                        continue
                    left, top, right, bottom = (float(value) for value in bbox)
                    sizes = [float(span.get("size", 0.0)) for span in spans if span.get("size")]
                    size = sum(sizes) / len(sizes) if sizes else 0.0
                    fonts = [str(span.get("font", "")) for span in spans if span.get("font")]
                    bold = any("bold" in font.lower() for font in fonts)
                    is_caps = text.strip().isupper()
                    entry = {
                        "global_idx": -1,
                        "page": page_number,
                        "line_idx": len(page_lines),
                        "text": text,
                        "size": size,
                        "bold": bold,
                        "is_caps": is_caps,
                        "left": left,
                        "right": right,
                        "top": top,
                        "bottom": bottom,
                        "is_toc": False,
                        "is_index": False,
                        "is_running": False,
                    }
                    if tracer and sample_budget > 0:
                        tracer.ev(
                            "pre_normalize_sample",
                            page=page_number,
                            line_idx=entry["line_idx"],
                            text=text,
                        )
                        sample_budget -= 1
                    page_lines.append(entry)

            height = float(page.rect.height)
            top_threshold = height * 0.18
            bottom_threshold = height * 0.85
            for entry in page_lines:
                normalised = _normalise_text(entry.get("text", ""))
                if not normalised:
                    continue
                if tracer and entry.get("line_idx", 0) < 5:
                    tracer.ev(
                        "normalized_line",
                        page=page_number,
                        line_idx=entry.get("line_idx", 0),
                        raw=entry.get("text", ""),
                        normalised=normalised,
                    )
                if entry["top"] <= top_threshold:
                    header_counter[normalised] += 1
                elif entry["bottom"] >= bottom_threshold:
                    footer_counter[normalised] += 1

            pages.append(
                {
                    "number": page_number,
                    "height": height,
                    "lines": page_lines,
                }
            )

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

    all_lines: list[dict] = []
    global_idx = 0

    for page in pages:
        page_number = page["number"]
        page_lines = page["lines"]
        texts = [line.get("text", "") for line in page_lines]
        is_toc_page = _is_toc_like(texts, page_number)
        is_index_page = _is_index_like(texts)
        if suppress_toc and (is_toc_page or is_index_page):
            excluded_pages.add(page_number)
            if tracer:
                tracer.ev(
                    "toc_detected",
                    page=page_number,
                    reason="index" if is_index_page else "toc",
                    sample=texts[:6],
                )

        for entry in page_lines:
            normalised = _normalise_text(entry.get("text", ""))
            if suppress_running and normalised in running_markers:
                entry["is_running"] = True
            entry["is_toc"] = is_toc_page
            entry["is_index"] = is_index_page
            entry["global_idx"] = global_idx
            all_lines.append(entry)
            global_idx += 1

    if tracer:
        tracer.ev(
            "doc_stats",
            pages=len(pages),
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
