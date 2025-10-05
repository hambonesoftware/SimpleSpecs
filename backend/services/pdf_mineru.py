"""Integration helpers for the MinerU PDF parser."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

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
from .mineru_adapter import MinerUConfig, NormObj, load_mineru_client, parse_with_mineru
from .pdf_native import NativePdfParser

__all__ = [
    "MinerUPdfParser",
    "MinerUUnavailableError",
    "check_mineru_availability",
    "mineru_blocks_to_parsed_objects",
]


class MinerUUnavailableError(RuntimeError):
    """Raised when the MinerU engine cannot be used."""


def _load_mineru_module() -> tuple[Any | None, str | None, str | None]:
    """Attempt to import the MinerU client library."""

    try:
        client = load_mineru_client()
    except ModuleNotFoundError as exc:
        return None, None, str(exc)
    except Exception as exc:  # pragma: no cover - optional dependency
        return None, "mineru.cli.client", str(exc)
    return client, "mineru", None


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


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return None


def _normalize_page(value: Any) -> int | None:
    page = _coerce_int(value)
    if page is None:
        return None
    # MinerU typically reports pages as 1-based indexes.
    if page > 0:
        return page - 1
    return page


def _normalize_bbox(value: Any) -> list[float] | None:
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


def _sanitize_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def mineru_blocks_to_parsed_objects(
    blocks: Iterable[NormObj],
    file_id: str,
    engine: str = "mineru",
) -> List[ParsedObject]:
    """Convert normalized MinerU blocks into SimpleSpecs parsed objects."""

    objects: list[ParsedObject] = []
    for order_index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue

        metadata = dict(block.get("meta") or {})
        metadata.setdefault("source", block.get("source", "mineru"))
        metadata.setdefault("mineru_kind", block.get("kind"))
        metadata.setdefault("mineru_block_id", block.get("id"))
        metadata["engine"] = engine

        base_kwargs = {
            "object_id": f"{file_id}-mineru-{order_index:06d}",
            "file_id": file_id,
            "text": _sanitize_text(block.get("text")),
            "page_index": _normalize_page(block.get("page")),
            "bbox": _normalize_bbox(block.get("bbox")),
            "order_index": order_index,
            "metadata": metadata,
        }

        kind = (block.get("kind") or "paragraph").lower()
        if kind == "heading":
            level = _coerce_int(metadata.get("level")) or 1
            obj = HeaderObject(
                **base_kwargs,
                level=level,
                number=metadata.get("number"),
                normalized_text=metadata.get("normalized_text"),
                path=metadata.get("path"),
            )
        elif kind == "table":
            obj = TableObject(
                **base_kwargs,
                n_rows=_coerce_int(metadata.get("n_rows")),
                n_cols=_coerce_int(metadata.get("n_cols")),
                has_header_row=_coerce_bool(metadata.get("has_header_row")),
                markdown=base_kwargs["text"],
            )
        elif kind == "figure":
            obj = FigureObject(
                **base_kwargs,
                caption=base_kwargs["text"],
                ref_id=metadata.get("ref_id"),
            )
        elif kind == "line":
            words_payload = metadata.get("words") or []
            words: list[Word] = []
            for word in words_payload:
                if isinstance(word, Word):
                    words.append(word)
                elif isinstance(word, dict):
                    words.append(Word.model_validate(word))
                elif isinstance(word, str):
                    words.append(Word(text=word))
            obj = LineObject(
                **base_kwargs,
                words=words,
                is_blank=metadata.get("is_blank"),
                line_index=_coerce_int(metadata.get("line_index")),
            )
        else:
            line_span = metadata.get("line_span")
            processed_span: list[int] | None = None
            if isinstance(line_span, (list, tuple)):
                processed_span = []
                for entry in line_span:
                    value = _coerce_int(entry)
                    if value is None:
                        processed_span = None
                        break
                    processed_span.append(value)
            obj = ParagraphObject(
                **base_kwargs,
                line_span=processed_span,
                paragraph_index=_coerce_int(metadata.get("paragraph_index")),
            )
        objects.append(obj)

    return objects


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
        resolved = Path(file_path).resolve()
        file_id = resolved.parent.parent.name or resolved.stem
        if self._module_name != "mineru":  # pragma: no cover - optional dependency
            raise MinerUUnavailableError("MinerU client library is not available.")
        return self._parse_mineru(str(resolved), file_id)

    def _parse_mineru(self, file_path: str, file_id: str) -> list[ParsedObject]:
        pdf_path = Path(file_path)
        try:
            pdf_bytes = pdf_path.read_bytes()
        except OSError as exc:  # pragma: no cover - filesystem edge case
            raise MinerUUnavailableError(str(exc)) from exc

        cfg = MinerUConfig()
        for key, value in (self.settings.MINERU_MODEL_OPTS or {}).items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

        try:
            blocks, _ = parse_with_mineru(file_id, pdf_bytes, pdf_path.name, cfg)
        except Exception as exc:  # pragma: no cover - optional dependency
            raise MinerUUnavailableError(str(exc)) from exc

        objects = mineru_blocks_to_parsed_objects(blocks, file_id, engine="mineru")
        if not objects:
            native_fallback = NativePdfParser()
            return [
                obj.model_copy(
                    update={
                        "metadata": {
                            **obj.metadata,
                            "engine": "mineru",
                            "mineru_mode": cfg.mode,
                            "source": "native_fallback",
                        }
                    }
                )
                for obj in native_fallback.parse_pdf(file_path)
            ]
        return objects
