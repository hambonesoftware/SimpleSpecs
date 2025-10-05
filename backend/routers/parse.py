"""MinerU parsing endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from ..services.mineru_adapter import MinerUConfig, parse_with_mineru
from ..services.pdf_mineru import mineru_blocks_to_parsed_objects
from ..store import upload_objects_path, write_jsonl

router = APIRouter(prefix="/api")


@router.post("/parse/mineru")
async def parse_mineru(
    upload_id: str = Form(...),
    file: UploadFile = File(...),
    mode: Optional[str] = Form(None),
) -> dict:
    try:
        pdf_bytes = await file.read()
        filename = file.filename or "document.pdf"
        cfg = MinerUConfig()
        if mode in {"server", "library"}:
            cfg.mode = mode

        blocks, artifacts_dir = parse_with_mineru(upload_id, pdf_bytes, filename, cfg)
        parsed_objects = mineru_blocks_to_parsed_objects(blocks, upload_id, engine="mineru")
        for obj in parsed_objects:
            obj.metadata.setdefault("original_filename", filename)

        write_jsonl(
            upload_objects_path(upload_id),
            [obj.model_dump(mode="python") for obj in parsed_objects],
        )
        return {
            "upload_id": upload_id,
            "count": len(parsed_objects),
            "artifacts_dir": str(artifacts_dir),
            "mode": cfg.mode,
        }
    except Exception as exc:  # pragma: no cover - FastAPI error propagation
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MinerU parse failed: {exc}",
        ) from exc
