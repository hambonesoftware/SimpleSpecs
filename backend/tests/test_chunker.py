"""Unit tests for the chunking helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models import ParsedObject, SectionNode, SectionSpan
import backend.services.chunker as chunker
from backend.services.chunker import compute_section_spans


def _make_object(file_id: str, index: int, text: str) -> ParsedObject:
    return ParsedObject(
        object_id=f"{file_id}-obj-{index}",
        file_id=file_id,
        kind="text",
        text=text,
        page_index=0,
        bbox=None,
        order_index=index,
    )


def test_compute_section_spans() -> None:
    """Objects after each header are grouped until the next header."""

    file_id = "file"
    objects = [
        _make_object(file_id, 0, "Alpha"),
        _make_object(file_id, 1, "Alpha details 1"),
        _make_object(file_id, 2, "Alpha details 2"),
        _make_object(file_id, 3, "Gamma"),
        _make_object(file_id, 4, "Gamma details"),
        _make_object(file_id, 5, "Delta"),
        _make_object(file_id, 6, "Delta details"),
    ]

    section_alpha = SectionNode(
        section_id="sec-alpha",
        file_id=file_id,
        title="Alpha",
        depth=1,
        children=[],
        span=SectionSpan(
            start_object=objects[0].object_id,
            end_object=objects[2].object_id,
        ),
    )
    section_gamma = SectionNode(
        section_id="sec-gamma",
        file_id=file_id,
        title="Gamma",
        depth=2,
        children=[],
        span=SectionSpan(
            start_object=objects[3].object_id,
            end_object=objects[4].object_id,
        ),
    )
    section_delta = SectionNode(
        section_id="sec-delta",
        file_id=file_id,
        title="Delta",
        depth=2,
        children=[],
        span=SectionSpan(
            start_object=objects[5].object_id,
            end_object=objects[6].object_id,
        ),
    )
    section_parent = SectionNode(
        section_id="sec-parent",
        file_id=file_id,
        title="Parent",
        depth=1,
        children=[section_gamma, section_delta],
    )
    root = SectionNode(
        section_id="root",
        file_id=file_id,
        title="Document",
        depth=0,
        children=[section_alpha, section_parent],
    )

    mapping = compute_section_spans(root, objects)

    assert mapping["sec-alpha"] == [objects[1].object_id, objects[2].object_id]
    assert mapping["sec-gamma"] == [objects[4].object_id]
    assert mapping["sec-delta"] == [objects[6].object_id]
    assert mapping["sec-parent"] == [
        objects[4].object_id,
        objects[6].object_id,
    ]
    assert mapping["root"] == [obj.object_id for obj in objects]
    assert set(mapping.keys()) == {
        "root",
        "sec-alpha",
        "sec-delta",
        "sec-gamma",
        "sec-parent",
    }


def _make_custom_object(
    file_id: str,
    index: int,
    text: str,
    *,
    kind: str = "text",
    page: int | None = 0,
) -> ParsedObject:
    return ParsedObject(
        object_id=f"{file_id}-obj-{index}",
        file_id=file_id,
        kind=kind,
        text=text,
        page_index=page,
        bbox=None,
        order_index=index,
    )


def test_canonical_artifacts_and_shards() -> None:
    file_id = "file"
    objects = [
        _make_custom_object(file_id, 0, "1 Alpha"),
        _make_custom_object(file_id, 1, "Alpha body first sentence."),
        _make_custom_object(file_id, 2, "Alpha body second sentence."),
        _make_custom_object(file_id, 3, "1.1 Beta", page=1),
        _make_custom_object(file_id, 4, "Beta body includes a table.", page=1),
        _make_custom_object(
            file_id,
            5,
            "Table 1: Dimensions",
            kind="table",
            page=1,
        ),
    ]

    section_alpha = SectionNode(
        section_id="sec-alpha",
        file_id=file_id,
        title="Alpha",
        depth=1,
        children=[],
        span=SectionSpan(
            start_object=objects[0].object_id,
            end_object=objects[2].object_id,
        ),
    )
    section_beta = SectionNode(
        section_id="sec-beta",
        file_id=file_id,
        title="Beta",
        depth=1,
        children=[],
        span=SectionSpan(
            start_object=objects[3].object_id,
            end_object=objects[5].object_id,
        ),
    )
    root = SectionNode(
        section_id="root",
        file_id=file_id,
        title="Document",
        depth=0,
        children=[section_alpha, section_beta],
    )

    computation = chunker._compute_chunks(root, objects)
    canonical, shards = chunker._build_canonical_artifacts(computation)

    alpha_entry = next(item for item in canonical if item["section_id"] == "sec-alpha")
    beta_entry = next(item for item in canonical if item["section_id"] == "sec-beta")

    assert alpha_entry["object_index_span"] == [1, 3]
    assert "Alpha body first sentence." in alpha_entry["text"]
    assert alpha_entry["header_path"] == ["Document"]

    assert beta_entry["object_index_span"] == [4, 6]
    assert beta_entry["outbound_object_ids"] == [objects[5].object_id]

    beta_shards = [item for item in shards if item["section_id"] == "sec-beta"]
    assert beta_shards
    assert beta_shards[0]["text"].startswith("Document > Beta")
    assert beta_shards[0]["parent_section_id"] == "root"
