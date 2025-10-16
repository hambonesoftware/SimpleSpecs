from __future__ import annotations

from pathlib import Path

import json

from backend.cli import specs_index, specs_query
from backend.config import get_settings
from backend.models import LineObject, ParagraphObject, SectionNode, SectionSpan


def test_specs_cli_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SIMPLS_RAG_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("SIMPLS_RAG_LIGHT_MODE", "1")
    monkeypatch.setenv("SIMPLS_RAG_DEBUG", "0")
    get_settings.cache_clear()

    settings = get_settings()
    file_id = "cli-sample"
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
    ]
    with (parsed_dir / "objects.json").open("w", encoding="utf-8") as handle:
        json.dump([obj.model_dump(mode="json") for obj in objects], handle, indent=2)

    section = SectionNode(
        section_id="sec-1",
        file_id=file_id,
        title="Electrical Requirements",
        depth=1,
        number="1",
        span=SectionSpan(
            start_object=objects[0].object_id,
            end_object=objects[-1].object_id,
        ),
        children=[],
    )
    root = SectionNode(
        section_id="root",
        file_id=file_id,
        title="Document",
        depth=0,
        children=[section],
    )
    with (headers_dir / "sections.json").open("w", encoding="utf-8") as handle:
        json.dump(root.model_dump(mode="json"), handle, indent=2)

    exit_code = specs_index.main([file_id])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Indexed" in captured.out

    query_code = specs_query.main(
        ["--file-id", file_id, "--q", "24 VDC safety relay", "--k", "2"]
    )
    query_out = capsys.readouterr()
    assert query_code == 0
    assert "24 VDC" in query_out.out

    get_settings.cache_clear()
