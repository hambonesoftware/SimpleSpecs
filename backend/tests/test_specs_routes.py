from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app
from backend.models import LineObject, ParagraphObject, SectionNode, SectionSpan


def _prepare_artifacts(tmp_path: Path) -> str:
    artifacts_dir = tmp_path / "artifacts"
    index_dir = tmp_path / "index"
    os.environ["SIMPLS_ARTIFACTS_DIR"] = str(artifacts_dir)
    os.environ["SIMPLS_RAG_INDEX_DIR"] = str(index_dir)
    os.environ["SIMPLS_RAG_LIGHT_MODE"] = "1"
    get_settings.cache_clear()
    settings = get_settings()

    file_id = "unit-spec"
    artifact_root = Path(settings.ARTIFACTS_DIR) / file_id
    parsed_dir = artifact_root / "parsed"
    headers_dir = artifact_root / "headers"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    headers_dir.mkdir(parents=True, exist_ok=True)

    objects = [
        LineObject(
            object_id=f"{file_id}-obj-0",
            file_id=file_id,
            text="Electrical Requirements",
            page_index=0,
            order_index=0,
            paragraph_index=0,
        ),
        ParagraphObject(
            object_id=f"{file_id}-obj-1",
            file_id=file_id,
            text="The safety relay shall operate at 24 VDC supply.",
            page_index=0,
            order_index=1,
            paragraph_index=1,
        ),
        ParagraphObject(
            object_id=f"{file_id}-obj-2",
            file_id=file_id,
            text="Maintain 5 mm clearance around the enclosure.",
            page_index=0,
            order_index=2,
            paragraph_index=2,
        ),
        LineObject(
            object_id=f"{file_id}-obj-3",
            file_id=file_id,
            text="Software",
            page_index=1,
            order_index=3,
            paragraph_index=3,
        ),
        ParagraphObject(
            object_id=f"{file_id}-obj-4",
            file_id=file_id,
            text="Software version should be 1.2.0 or later.",
            page_index=1,
            order_index=4,
            paragraph_index=4,
        ),
    ]
    with (parsed_dir / "objects.json").open("w", encoding="utf-8") as handle:
        json.dump([obj.model_dump(mode="json") for obj in objects], handle, indent=2)

    section_elec = SectionNode(
        section_id="sec-1",
        file_id=file_id,
        title="Electrical Requirements",
        depth=1,
        number="1",
        span=SectionSpan(
            start_object=objects[0].object_id,
            end_object=objects[2].object_id,
        ),
        children=[],
    )
    section_soft = SectionNode(
        section_id="sec-2",
        file_id=file_id,
        title="Software",
        depth=1,
        number="2",
        span=SectionSpan(
            start_object=objects[3].object_id,
            end_object=objects[4].object_id,
        ),
        children=[],
    )
    root = SectionNode(
        section_id="root",
        file_id=file_id,
        title="Document",
        depth=0,
        children=[section_elec, section_soft],
    )
    with (headers_dir / "sections.json").open("w", encoding="utf-8") as handle:
        json.dump(root.model_dump(mode="json"), handle, indent=2)

    return file_id


def test_spec_endpoints_roundtrip(tmp_path) -> None:
    file_id = _prepare_artifacts(tmp_path)
    app = create_app()
    client = TestClient(app)

    extract_response = client.post("/api/specs/extract", json={"file_id": file_id})
    assert extract_response.status_code == 200
    extracted = extract_response.json()
    assert len(extracted) == 3
    assert any("24 VDC" in item["spec_text"] for item in extracted)

    index_response = client.post("/api/specs/index", json={"file_id": file_id})
    assert index_response.status_code == 200
    assert index_response.json()["indexed"] == 3

    search_response = client.post(
        "/api/specs/search",
        json={"file_id": file_id, "query": "24 VDC safety", "top_k": 2},
    )
    assert search_response.status_code == 200
    hits = search_response.json()
    assert hits
    assert any("24 VDC" in hit["text"] for hit in hits)

    export_response = client.post("/api/specs/export", json={"file_id": file_id})
    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["file_id"] == file_id
    assert len(export_payload["specs"]) == 3

    for key in ["SIMPLS_ARTIFACTS_DIR", "SIMPLS_RAG_INDEX_DIR", "SIMPLS_RAG_LIGHT_MODE"]:
        os.environ.pop(key, None)
    get_settings.cache_clear()
