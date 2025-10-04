from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..models import ParsedObject
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
        for item in result if isinstance(result, list) else []:
            kind = item.get("kind", "text")
            text = item.get("text")
            page_index = item.get("page_index")
            bbox = item.get("bbox")
            metadata = item.get("metadata", {})
            metadata = {**metadata, "engine": engine}
            objects.append(
                ParsedObject(
                    object_id=f"{file_id}-mineru-{order_index:06d}",
                    file_id=file_id,
                    kind=kind,
                    text=text,
                    page_index=page_index,
                    bbox=bbox,
                    order_index=order_index,
                    metadata=metadata,
                )
            )
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
