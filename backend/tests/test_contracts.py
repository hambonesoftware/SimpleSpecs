"""Contract tests for Pydantic models."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models import BoundingBox, ParsedObject, SectionNode, SpecItem


def test_models_schema() -> None:
    bbox = BoundingBox(x0=0, y0=0, x1=10, y1=10)
    parsed = ParsedObject(
        object_id="file-obj-1",
        file_id="file",
        kind="text",
        text="example",
        page_index=0,
        bbox=[bbox.x0, bbox.y0, bbox.x1, bbox.y1],
        order_index=0,
    )
    section = SectionNode(
        section_id="sec-root",
        file_id="file",
        title="Root",
        depth=0,
        children=[
            SectionNode(
                section_id="sec-child",
                file_id="file",
                title="Child",
                depth=1,
            )
        ],
    )
    spec = SpecItem(
        spec_id="spec-1",
        file_id="file",
        section_id=section.section_id,
        section_title=section.title,
        spec_text="System shall be mockable.",
        source_object_ids=[parsed.object_id],
    )

    assert parsed.kind == "text"
    assert parsed.order_index == 0
    assert section.children[0].depth == 1
    assert spec.source_object_ids == [parsed.object_id]
    assert parsed.model_dump()["bbox"][2] == 10
