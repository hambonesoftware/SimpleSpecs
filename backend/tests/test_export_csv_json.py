from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.main import create_app

client = TestClient(create_app())
settings = get_settings()


def _run_pipeline() -> str:
    content = (
        "1. Overview\n"
        "This document outlines requirements.\n"
        "1.1 Scope\n"
        "Maximum pressure is 20 MPa.\n"
        "1.2 Materials\n"
        "Use ASTM A36 steel throughout.\n"
    ).encode("utf-8")
    ingest = client.post(
        "/ingest",
        files={"file": ("sample.txt", BytesIO(content), "text/plain")},
    )
    assert ingest.status_code == 200
    file_id = ingest.json()["file_id"]

    headers = client.post(f"/headers/{file_id}/find")
    assert headers.status_code == 200

    chunks = client.post(f"/chunks/{file_id}")
    assert chunks.status_code == 200

    specs = client.post(f"/specs/{file_id}/find")
    assert specs.status_code == 200

    return file_id


def test_export_formats() -> None:
    file_id = _run_pipeline()

    qa_response = client.get(f"/qa/{file_id}")
    assert qa_response.status_code == 200
    qa_payload = qa_response.json()
    assert qa_payload["file_id"] == file_id
    qa_section = qa_payload["qa"]
    assert {"coverage", "consistency", "determinism", "warnings"} <= qa_section.keys()
    assert isinstance(qa_section["warnings"], list)

    export_json_1 = client.get(f"/export/{file_id}")
    assert export_json_1.status_code == 200
    assert export_json_1.headers["content-type"].startswith("application/json")
    assert export_json_1.headers["content-disposition"] == (
        f'attachment; filename="export_{file_id}.json"'
    )
    json_payload = export_json_1.json()
    assert json_payload["file_id"] == file_id
    assert isinstance(json_payload["sections"], list)
    assert isinstance(json_payload["specs"], list)

    export_json_2 = client.get(f"/export/{file_id}")
    assert export_json_2.status_code == 200
    assert export_json_1.content == export_json_2.content

    export_csv_1 = client.get(f"/export/{file_id}", params={"fmt": "csv"})
    assert export_csv_1.status_code == 200
    assert export_csv_1.headers["content-type"].startswith("text/csv")
    assert export_csv_1.headers["content-disposition"] == (
        f'attachment; filename="export_{file_id}.csv"'
    )
    csv_lines = export_csv_1.text.splitlines()
    assert csv_lines
    assert (
        csv_lines[0]
        == "spec_id,file_id,section_id,section_number,section_title,spec_text,confidence,source_object_ids"
    )

    export_csv_2 = client.get(f"/export/{file_id}", params={"fmt": "csv"})
    assert export_csv_2.status_code == 200
    assert export_csv_1.content == export_csv_2.content

    missing = client.get("/export/unknown-file")
    assert missing.status_code == 404

    specs_path = Path(settings.ARTIFACTS_DIR) / file_id / "specs" / "specs.json"
    assert specs_path.exists()
    backup_path = specs_path.with_suffix(".bak")
    specs_path.rename(backup_path)
    try:
        missing_specs = client.get(f"/export/{file_id}")
        assert missing_specs.status_code == 404

        qa_missing = client.get(f"/qa/{file_id}")
        assert qa_missing.status_code == 200
        qa_payload_missing = qa_missing.json()["qa"]
        assert qa_payload_missing["consistency"]["specs_present"] is False
    finally:
        backup_path.rename(specs_path)

    # Reload QA to ensure restored artifacts behave deterministically.
    qa_restored = client.get(f"/qa/{file_id}")
    assert qa_restored.status_code == 200
