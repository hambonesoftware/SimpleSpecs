"""Upload and parsing routes for document ingestion."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated, Iterable

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from ..config import Settings, get_settings
from ..models import (
    FIGURE_KIND,
    LINE_KIND,
    PARAGRAPH_KIND,
    PARSED_OBJECT_ADAPTER,
    PARSED_OBJECT_TYPES,
    ParsedObject,
)
from ..services.parse_docx import parse_docx
from ..services.parse_txt import parse_txt
from ..services.pdf_mineru import MinerUUnavailableError
from ..services.pdf_parser import select_pdf_parser

ingest_router = APIRouter(tags=["ingest"])


def _ensure_order(
    objects: Iterable[ParsedObject], file_id: str
) -> list[ParsedObject]:
    ordered: list[ParsedObject] = []
    for idx, obj in enumerate(objects):
        if not isinstance(obj, PARSED_OBJECT_TYPES):
            obj = PARSED_OBJECT_ADAPTER.validate_python(obj)
        updates = {
            "file_id": file_id,
            "order_index": idx,
        }
        if not getattr(obj, "object_id", None):
            updates["object_id"] = f"{file_id}-{idx:06d}"
        ordered.append(obj.model_copy(update=updates))
    return ordered


def _write_objects_json(target: Path, objects: list[ParsedObject]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump([obj.model_dump(mode="json") for obj in objects], handle, indent=2)


def _load_objects_json(path: Path) -> list[ParsedObject]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [PARSED_OBJECT_ADAPTER.validate_python(item) for item in data]


def _validate_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type.",
        )
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in {"pdf", "docx", "txt"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type.",
        )
    return extension


def _check_size_limit(data: bytes, settings: Settings) -> None:
    max_bytes = settings.MAX_FILE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File exceeds maximum allowed size.",
        )


def _is_ocr_available() -> bool:
    try:
        import importlib.util

        return any(
            importlib.util.find_spec(name) is not None
            for name in ("ocrmypdf", "pytesseract")
        )
    except Exception:
        return False


def _resolve_engine(engine_value: str | None, settings: Settings) -> str:
    if engine_value is None:
        return settings.PDF_ENGINE
    normalized = engine_value.lower()
    if normalized not in {"native", "mineru", "auto"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid engine selection.",
        )
    return normalized


@ingest_router.post("/ingest", summary="Upload and parse a document")
async def upload_and_parse(
    file: UploadFile | None = File(None),
    engine: Annotated[str | None, Form()] = None,
) -> dict[str, str | int]:
    """Persist an uploaded file and parse it into structured objects."""

    settings = get_settings()
    if file is None:
        file_id = uuid.uuid5(uuid.NAMESPACE_URL, "simplespecs/mock").hex[:8]
        artifact_root = Path(settings.ARTIFACTS_DIR) / file_id
        parsed_dir = artifact_root / "parsed"
        _write_objects_json(parsed_dir / "objects.json", [])
        return {"file_id": file_id, "object_count": 0, "status": "queued"}

    extension = _validate_extension(file.filename)
    content = await file.read()
    _check_size_limit(content, settings)

    file_id = uuid.uuid4().hex
    artifact_root = Path(settings.ARTIFACTS_DIR) / file_id
    source_dir = artifact_root / "source"
    parsed_dir = artifact_root / "parsed"
    source_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    document_path = source_dir / f"document.{extension}"
    document_path.write_bytes(content)

    try:
        if extension == "pdf":
            selected_engine = _resolve_engine(engine, settings)
            try:
                parser = select_pdf_parser(
                    settings=settings,
                    file_path=str(document_path),
                    override=selected_engine,
                )
            except MinerUUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_501_NOT_IMPLEMENTED,
                    detail={"error": "mineru_not_available", "message": str(exc)},
                ) from exc
            try:
                objects = parser.parse_pdf(str(document_path))
            except MinerUUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_501_NOT_IMPLEMENTED,
                    detail={"error": "mineru_not_available", "message": str(exc)},
                ) from exc
        elif extension == "docx":
            objects = parse_docx(str(document_path))
        else:
            objects = parse_txt(str(document_path))
    finally:
        await file.close()

    ordered_objects = _ensure_order(objects, file_id)

    if extension == "pdf":
        textual_kinds = {LINE_KIND, PARAGRAPH_KIND}
        has_text = any(
            obj.kind in textual_kinds and (obj.text or "").strip() for obj in ordered_objects
        )
        has_images = any(obj.kind == FIGURE_KIND for obj in ordered_objects)
        selected_engine = _resolve_engine(engine, settings)
        if selected_engine != "mineru" and not has_text and has_images and not _is_ocr_available():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document appears scanned. Enable OCR or MinerU for processing.",
            )

    _write_objects_json(parsed_dir / "objects.json", ordered_objects)

    return {
        "file_id": file_id,
        "object_count": len(ordered_objects),
        "status": "processed",
    }


@ingest_router.get("/parsed/{file_id}", summary="Retrieve parsed objects")
def get_parsed_objects(file_id: str) -> list[ParsedObject]:
    """Return persisted parsed objects for a file."""

    settings = get_settings()
    parsed_path = Path(settings.ARTIFACTS_DIR) / file_id / "parsed" / "objects.json"
    if not parsed_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not parsed.")
    return _load_objects_json(parsed_path)
