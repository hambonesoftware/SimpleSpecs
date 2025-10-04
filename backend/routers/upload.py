"""Upload and parsed object retrieval endpoints."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from ..models import ObjectsResponse, PARSED_OBJECT_ADAPTER, ParsedObject, UploadResponse
from ..services.parsing import parse_document
from ..store import read_jsonl, upload_objects_path, write_jsonl

router = APIRouter(prefix="/api")


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    """Upload a document, parse it immediately and persist the parsed objects."""

    filename = file.filename or "document"
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {extension or 'unknown'}",
        )

    temp_dir = Path(os.getenv("TMPDIR", "/tmp"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"upload_{uuid.uuid4().hex}{extension}"

    try:
        with temp_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)

        parsed_objects = parse_document(temp_path)
        upload_id = uuid.uuid4().hex
        jsonl_path = upload_objects_path(upload_id)
        write_jsonl(jsonl_path, parsed_objects)
        return UploadResponse(upload_id=upload_id, object_count=len(parsed_objects))
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            # Best effort cleanup
            pass


@router.get("/objects", response_model=ObjectsResponse)
async def get_objects(
    upload_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=2000),
) -> ObjectsResponse:
    """Return paginated parsed objects for a previous upload."""

    path = upload_objects_path(upload_id)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    raw_objects = read_jsonl(path)
    objects = [PARSED_OBJECT_ADAPTER.validate_python(obj) for obj in raw_objects]

    total = len(objects)
    start = (page - 1) * page_size
    end = start + page_size
    if start >= total:
        return ObjectsResponse(items=[], total=total)

    return ObjectsResponse(items=objects[start:end], total=total)
