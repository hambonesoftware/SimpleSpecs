from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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

__all__ = [
    "MinerUPdfParser",
    "MinerUUnavailableError",
    "check_mineru_availability",
]


class MinerUUnavailableError(RuntimeError):
    """Raised when the MinerU engine cannot be used."""


def _load_mineru_module() -> tuple[Any | None, str | None, str | None]:
    """Attempt to import the MinerU client library."""

    try:
        module = importlib.import_module("mineru")
    except ModuleNotFoundError as exc:
        return None, None, str(exc)
    except Exception as exc:  # pragma: no cover - optional dependency
        return None, "mineru", str(exc)
    return module, "mineru", None


def check_mineru_availability(
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """Return whether MinerU can be used and why it is unavailable otherwise."""

    settings = settings or get_settings()
    if not settings.MINERU_ENABLED:
        return False, "MinerU is disabled in settings."

    module, _module_name, error_message = _load_mineru_module()
    if module is None:
        if error_message:
            return False, f"MinerU client library could not be imported: {error_message}"
        return False, "MinerU client library is not installed."

    return True, None


@dataclass
class MinerUPdfParser:
    """Proxy parser that delegates to the MinerU client when available."""

    settings: Settings | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or get_settings()
        if not self.settings.MINERU_ENABLED:
            raise MinerUUnavailableError("MinerU is disabled in settings.")
        self._module, self._module_name, error_message = _load_mineru_module()
        if self._module is None:
            if error_message:
                raise MinerUUnavailableError(
                    f"MinerU client library could not be imported: {error_message}"
                )
            raise MinerUUnavailableError("MinerU client library is not installed.")

    def parse_pdf(self, file_path: str) -> list[ParsedObject]:
        file_id = Path(file_path).resolve().parent.parent.name
        if self._module_name != "mineru":  # pragma: no cover - optional dependency
            raise MinerUUnavailableError("MinerU client library is not available.")
        return self._parse_mineru(file_path, file_id)

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

        def _coerce_bbox(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, (list, tuple)) and len(value) == 4:
                try:
                    return [float(v) for v in value]
                except (TypeError, ValueError):
                    return None
            if isinstance(value, dict):
                keys = ("x0", "y0", "x1", "y1")
                if all(key in value for key in keys):
                    try:
                        return [float(value[key]) for key in keys]
                    except (TypeError, ValueError):
                        return None
            return None

        def _coerce_text(item: dict[str, Any]) -> str | None:
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                return value
            for key in ("content", "value", "text_content", "caption"):
                text_value = item.get(key)
                if isinstance(text_value, str) and text_value.strip():
                    return text_value
            return value if isinstance(value, str) else None

        def _iter_items(payload: Any, inherited_page: int | None = None) -> Iterable[dict[str, Any]]:
            if payload is None:
                return
            if isinstance(payload, list):
                for entry in payload:
                    yield from _iter_items(entry, inherited_page=inherited_page)
                return
            if not isinstance(payload, dict):
                return

            looks_like_item = any(key in payload for key in ("kind", "type", "category", "text"))
            if looks_like_item:
                page_value = _coerce_int(payload.get("page_index"))
                if page_value is None:
                    for key in ("page", "page_no", "page_num", "page_number"):
                        page_value = _coerce_int(payload.get(key))
                        if page_value is not None:
                            break
                normalized = dict(payload)
                if inherited_page is not None and normalized.get("page_index") is None:
                    normalized["page_index"] = inherited_page
                elif page_value is not None:
                    normalized["page_index"] = page_value
                yield normalized

            for key in (
                "elements",
                "items",
                "blocks",
                "paragraphs",
                "objects",
                "result",
                "data",
                "layout",
                "children",
            ):
                if key in payload:
                    yield from _iter_items(payload[key], inherited_page=inherited_page)

            for key in ("pages", "page_items", "page_list"):
                if key not in payload:
                    continue
                pages = payload[key]
                if not isinstance(pages, list):
                    continue
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    page_index = _coerce_int(page.get("page_index"))
                    if page_index is None:
                        page_index = _coerce_int(page.get("page"))
                    yield from _iter_items(page, inherited_page=page_index)

        for item in _iter_items(result):
            if not isinstance(item, dict):
                continue

            metadata = {**(item.get("metadata") or {}), "engine": engine}
            base_kwargs = {
                "object_id": f"{file_id}-mineru-{order_index:06d}",
                "file_id": file_id,
                "text": _coerce_text(item),
                "page_index": _coerce_int(item.get("page_index")) or _coerce_int(item.get("page")) or _coerce_int(item.get("page_no")),
                "bbox": _coerce_bbox(item.get("bbox")) or _coerce_bbox(item.get("box")) or _coerce_bbox(item.get("rect")) or _coerce_bbox(item.get("region")),
                "order_index": order_index,
                "metadata": metadata,
            }

            kind_value = item.get("kind") or item.get("type") or item.get("category") or "para"
            kind = str(kind_value).lower()
            if kind not in {"para", "paragraph", "text", "line", "textline", "header", "heading", "table", "figure", "image"}:
                metadata.setdefault("mineru_kind", kind)

            if kind in {"line", "textline"}:
                words_payload = item.get("words") or item.get("tokens") or []
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
            elif kind in {"para", "paragraph", "text", "list", "list_item", "bullet", "caption", "formula", "code"}:
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
            elif kind in {"header", "heading", "title"}:
                obj = HeaderObject(
                    **base_kwargs,
                    level=int(_coerce_int(item.get("level")) or 1),
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
                obj = ParagraphObject(
                    **base_kwargs,
                    paragraph_index=item.get("paragraph_index"),
                )
            objects.append(obj)
            order_index += 1
        if not objects:
            native_fallback = NativePdfParser()
            native_objects = native_fallback.parse_pdf(file_path)
            return [
                obj.model_copy(
                    update={"metadata": {**obj.metadata, "engine": engine, "source": "native_fallback"}}
                )
                for obj in native_objects
            ]
        return objects
