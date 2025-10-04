from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..models import (
    FigureObject,
    HeaderObject,
    LineObject,
    ParagraphObject,
    ParsedObject,
    TableObject,
    Word,
)
from .pdf_native import NativePdfParser

__all__ = ["MinerUPdfParser", "MinerUUnavailableError"]


class MinerUUnavailableError(RuntimeError):
    """Raised when the MinerU engine cannot be used."""


def _load_mineru_module() -> tuple[Any | None, str | None]:
    for name in ("mineru", "magic_pdf"):
        try:
            module = importlib.import_module(name)
            return module, name
        except ModuleNotFoundError:
            continue
        except Exception:
            return None, name
    return None, None


@dataclass
class MinerUPdfParser:
    """Proxy parser that delegates to the MinerU client when available."""

    settings: Settings | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or get_settings()
        if not self.settings.MINERU_ENABLED:
            raise MinerUUnavailableError("MinerU is disabled in settings.")
        self._module, self._module_name = _load_mineru_module()
        if self._module is None:
            raise MinerUUnavailableError("MinerU client library is not installed.")

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        file_id = Path(file_path).resolve().parent.parent.name
        if self._module_name == "magic_pdf":  # pragma: no cover - optional dependency
            return self._parse_magic_pdf(file_path, file_id)
        if self._module_name == "mineru":  # pragma: no cover - optional dependency
            return self._parse_mineru(file_path, file_id)
        raise MinerUUnavailableError("Unsupported MinerU module.")

    def _parse_magic_pdf(self, file_path: str, file_id: str) -> list[ParsedObject]:
        try:
            pipeline = getattr(self._module, "pipeline", None)
            if pipeline is None:
                raise AttributeError("pipeline not available")
            result = pipeline(file_path)
        except Exception as exc:  # pragma: no cover - optional dependency
            raise MinerUUnavailableError(str(exc)) from exc
        return self._normalize_mineru_output(result, file_path, file_id, engine="magic_pdf")

    def _parse_mineru(self, file_path: str, file_id: str) -> list[ParsedObject]:
        try:
            result = self._module.parse(file_path)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - optional dependency
            raise MinerUUnavailableError(str(exc)) from exc
        return self._normalize_mineru_output(result, file_path, file_id, engine="mineru")

    def _normalize_mineru_output(
        self, result: Any, file_path: str, file_id: str, engine: str
    ) -> list[ParsedObject]:
        if not result:  # pragma: no cover - optional dependency
            native_fallback = NativePdfParser()
            return [
                obj.model_copy(
                    update={
                        "metadata": {**obj.metadata, "engine": engine, "source": "native_fallback"}
                    }
                )
                for obj in native_fallback.parse_pdf(file_path)
            ]

        objects: list[ParsedObject] = []
        order_index = 0
        def _coerce_int(value: Any) -> int | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return None
                try:
                    return int(float(text))
                except ValueError:
                    return None
            return None

        for item in result if isinstance(result, list) else []:
            metadata = {**(item.get("metadata") or {}), "engine": engine}
            base_kwargs = {
                "object_id": f"{file_id}-mineru-{order_index:06d}",
                "file_id": file_id,
                "text": item.get("text"),
                "page_index": item.get("page_index"),
                "bbox": item.get("bbox"),
                "order_index": order_index,
                "metadata": metadata,
            }
            kind = (item.get("kind") or "para").lower()
            if kind in {"line", "textline"}:
                words_payload = item.get("words") or []
                words: list[Word] = []
                for word in words_payload:
                    if isinstance(word, Word):
                        words.append(word)
                    elif isinstance(word, str):
                        words.append(Word(text=word))
                    else:
                        words.append(Word.model_validate(word))
                obj = LineObject(
                    **base_kwargs,
                    words=words,
                    line_index=item.get("line_index"),
                    is_blank=item.get("is_blank"),
                )
            elif kind in {"para", "paragraph", "text"}:
                line_span = item.get("line_span")
                if isinstance(line_span, (list, tuple)):
                    processed_span = []
                    for entry in line_span:
                        try:
                            processed_span.append(int(entry))
                        except (TypeError, ValueError):
                            break
                    else:
                        line_span = processed_span
                else:
                    line_span = None
                obj = ParagraphObject(
                    **base_kwargs,
                    line_span=line_span if isinstance(line_span, list) else None,
                    paragraph_index=item.get("paragraph_index"),
                )
            elif kind in {"header", "heading"}:
                obj = HeaderObject(
                    **base_kwargs,
                    level=int(item.get("level", 1)),
                    number=item.get("number"),
                    normalized_text=item.get("normalized_text"),
                    path=item.get("path"),
                )
            elif kind == "table":
                obj = TableObject(
                    **base_kwargs,
                    n_rows=_coerce_int(item.get("n_rows")),
                    n_cols=_coerce_int(item.get("n_cols")),
                    has_header_row=item.get("has_header_row"),
                    markdown=item.get("markdown") or item.get("text"),
                )
            elif kind in {"figure", "image"}:
                obj = FigureObject(
                    **base_kwargs,
                    caption=item.get("caption"),
                    ref_id=item.get("ref_id"),
                )
            else:
                raise ValueError(f"Unsupported MinerU object kind: {kind}")
            objects.append(obj)
            order_index += 1
        if not objects:
            # As a last resort fall back to the native parser but annotate provenance.
            native_fallback = NativePdfParser()
            native_objects = native_fallback.parse_pdf(file_path)
            return [
                obj.model_copy(
                    update={"metadata": {**obj.metadata, "engine": engine, "source": "native_fallback"}}
                )
                for obj in native_objects
            ]
        return objects
