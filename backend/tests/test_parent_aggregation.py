"""Integration-style tests for parent aggregation logic."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.main import create_app
from backend.models import ParsedObject, SectionNode
from backend.services.chunker import compute_section_spans


def _iter_nodes(node: SectionNode) -> Iterator[SectionNode]:
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _iter_leaf_ids(node: SectionNode) -> list[str]:
    if not node.children:
        return [node.section_id]
    result: list[str] = []
    for child in node.children:
        result.extend(_iter_leaf_ids(child))
    return result


def test_parent_equals_union() -> None:
    """Parent text is union of children."""

    app = create_app()
    with TestClient(app) as client:
        content = (
            "1. Introduction\n"
            "Intro text line.\n"
            "1.1 Background\n"
            "Background line.\n"
            "2. Methods\n"
            "Methods text.\n"
            "3. Results\n"
            "Results text.\n"
        )
        response = client.post(
            "/ingest",
            files={"file": ("sample.txt", content.encode("utf-8"), "text/plain")},
        )
        assert response.status_code == 200
        file_id = response.json()["file_id"]

        headers_response = client.post(f"/headers/{file_id}/find")
        assert headers_response.status_code == 200
        root = SectionNode.model_validate(headers_response.json())

    settings = get_settings()
    artifact_root = Path(settings.ARTIFACTS_DIR) / file_id
    objects_path = artifact_root / "parsed" / "objects.json"

    try:
        with objects_path.open("r", encoding="utf-8") as handle:
            raw_objects = json.load(handle)
        objects = [ParsedObject.model_validate(item) for item in raw_objects]

        mapping = compute_section_spans(root, objects)
        mapping_again = compute_section_spans(root, objects)
        assert mapping == mapping_again

        for node in _iter_nodes(root):
            assert node.section_id in mapping

        leaf_ids = _iter_leaf_ids(root)
        assigned_objects: list[str] = []
        for leaf_id in leaf_ids:
            assigned_objects.extend(mapping[leaf_id])
        assert len(assigned_objects) == len(set(assigned_objects))

        for node in _iter_nodes(root):
            descendant_leaf_ids = _iter_leaf_ids(node)
            expected: list[str] = []
            for leaf_id in descendant_leaf_ids:
                expected.extend(mapping[leaf_id])
            assert mapping[node.section_id] == expected
    finally:
        shutil.rmtree(artifact_root, ignore_errors=True)
