from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.models import ParsedObject, SectionNode
from backend.services.specs import extract_specs_for_sections


class _DeterministicAdapter:
    """Adapter that returns predefined responses for each call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0

    def generate(self, prompt: str) -> str:  # noqa: D401 - simple deterministic stub
        if self._index >= len(self._responses):
            return self._responses[-1]
        response = self._responses[self._index]
        self._index += 1
        return response


def _build_section(section_id: str, file_id: str, title: str, number: str | None = None) -> SectionNode:
    return SectionNode(
        section_id=section_id,
        file_id=file_id,
        number=number,
        title=title,
        depth=1,
        children=[],
    )


def test_dedup_and_merge() -> None:
    """Specs with identical provenance are deduplicated while unique items persist."""

    original = os.environ.get("SIMPLS_ARTIFACTS_DIR")
    with tempfile.TemporaryDirectory() as tmp_dir:
        artifacts_dir = Path(tmp_dir) / "artifacts"
        os.environ["SIMPLS_ARTIFACTS_DIR"] = str(artifacts_dir)
        get_settings.cache_clear()

        file_id = "file-123"
        chunks_dir = artifacts_dir / file_id / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunk_map = {"sec-1": ["obj-1", "obj-2"], "sec-2": ["obj-1", "obj-2"]}
        (chunks_dir / "chunks.json").write_text(json.dumps(chunk_map))

        objects = [
            ParsedObject(
                object_id="obj-1",
                file_id=file_id,
                kind="text",
                text="- Maximum load 500 N",
                page_index=0,
                order_index=0,
            ),
            ParsedObject(
                object_id="obj-2",
                file_id=file_id,
                kind="text",
                text="- Allowable stress per ASTM A36",
                page_index=0,
                order_index=1,
            ),
        ]

        root = SectionNode(
            section_id="root",
            file_id=file_id,
            number=None,
            title="Root",
            depth=0,
            children=[
                _build_section("sec-1", file_id, "Specifications", "1"),
                _build_section("sec-2", file_id, "More Specifications", "2"),
            ],
        )

        adapter = _DeterministicAdapter(
            [
                "- Maximum load 500 N\n- Maximum load 500 N",
                "- Maximum load 500 N\n- Allowable stress per ASTM A36",
            ]
        )

        specs = extract_specs_for_sections(file_id, root, objects, adapter)

        assert [item.spec_text for item in specs] == [
            "Maximum load 500 N",
            "Allowable stress per ASTM A36",
        ]
        assert specs[0].section_id == "sec-1"
        assert specs[1].section_id == "sec-2"
        for item in specs:
            assert item.source_object_ids == ["obj-1", "obj-2"]

        persisted = artifacts_dir / file_id / "specs" / "specs.json"
        assert persisted.exists()
        payload = json.loads(persisted.read_text())
        assert [entry["spec_text"] for entry in payload] == [
            "Maximum load 500 N",
            "Allowable stress per ASTM A36",
        ]
    if original is None:
        os.environ.pop("SIMPLS_ARTIFACTS_DIR", None)
    else:
        os.environ["SIMPLS_ARTIFACTS_DIR"] = original
    get_settings.cache_clear()
