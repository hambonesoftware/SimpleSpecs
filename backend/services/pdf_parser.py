"""PDF parser abstractions for SimpleSpecs (Phase P0 stubs)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import Settings, get_settings
from ..models import ParsedObject
from .pdf_mineru import MinerUPdfParser, MinerUUnavailableError
from .pdf_native import NativePdfParser

__all__ = ["PdfParser", "select_pdf_parser", "MinerUUnavailableError"]


class PdfParser(Protocol):
    """Protocol describing PDF parsing behavior."""

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        """Parse a PDF into structured parsed objects."""


@dataclass
class AutoPdfParser:
    """Parser that selects between native and MinerU heuristically."""

    settings: Settings
    file_path: str

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        native_parser = NativePdfParser()
        native_objects = native_parser.parse_pdf(file_path)
        mineru_needed = self._should_use_mineru(native_objects)
        if mineru_needed:
            mineru_parser = MinerUPdfParser(self.settings)
            return mineru_parser.parse_pdf(file_path)
        return native_objects

    def _should_use_mineru(self, native_objects: list[ParsedObject]) -> bool:
        if not self.settings.MINERU_ENABLED:
            return False
        text_chars = sum(len(obj.text or "") for obj in native_objects if obj.kind == "text")
        has_images = any(obj.kind == "image" for obj in native_objects)
        has_tables = any(obj.kind == "table" for obj in native_objects)
        low_density = text_chars < 200
        return (low_density and has_images) or (not has_tables and has_images)


def select_pdf_parser(
    settings: Settings | None = None,
    file_path: str | None = None,
    override: str | None = None,
) -> PdfParser:
    """Return a parser instance for the configured engine."""

    settings = settings or get_settings()
    engine = (override or settings.PDF_ENGINE).lower()
    if engine == "native":
        return NativePdfParser()
    if engine == "mineru":
        return MinerUPdfParser(settings)
    if file_path is None:
        raise ValueError("file_path is required when selecting auto engine")
    return AutoPdfParser(settings=settings, file_path=file_path)
