"""Export endpoints."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..store import read_json, specs_path

router = APIRouter(prefix="/api")


@router.get("/export/specs.csv")
async def export_specs(upload_id: str = Query(...)) -> StreamingResponse:
    specs = read_json(specs_path(upload_id))
    if not specs:
        raise HTTPException(status_code=404, detail="No specifications available")

    header = [
        "spec_id",
        "file_id",
        "section_id",
        "section_number",
        "section_title",
        "spec_text",
        "confidence",
        "source_object_ids",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for item in specs:
        source_ids = item.get("source_object_ids") or []
        if not isinstance(source_ids, list):
            source_ids = [str(source_ids)]
        row = [
            item.get("spec_id", ""),
            item.get("file_id", ""),
            item.get("section_id", ""),
            item.get("section_number", ""),
            item.get("section_title", ""),
            item.get("spec_text", ""),
            item.get("confidence", ""),
            ",".join(str(value) for value in source_ids),
        ]
        writer.writerow(row)
    buffer.seek(0)
    headers = {"Content-Disposition": "attachment; filename=specs.csv"}
    return StreamingResponse(buffer, media_type="text/csv", headers=headers)
