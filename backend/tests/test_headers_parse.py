from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SIMPLS_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SIMPLS_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SIMPLS_LLAMACPP_URL", "")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_nested_list_parse_variants(monkeypatch, tmp_path):
    client = _create_client(monkeypatch, tmp_path)

    content = "\n".join(
        [
            "1. Introduction",
            "1.1 Background",
            "Methods",
            "Results",
        ]
    )
    response = client.post(
        "/ingest",
        files={"file": ("headers.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 200
    file_id = response.json()["file_id"]

    parsed_objects = client.get(f"/parsed/{file_id}")
    assert parsed_objects.status_code == 200
    objects_payload = parsed_objects.json()

    initial = client.get(f"/headers/{file_id}")
    assert initial.status_code == 200
    initial_tree = initial.json()

    discovery = client.post(f"/headers/{file_id}/find", params={"llm": "openrouter"})
    assert discovery.status_code == 200
    tree = discovery.json()
    assert tree["children"]
    assert tree != {}
    assert tree["file_id"] == file_id
    assert tree["section_id"].endswith("-root")
    assert tree["children"], "Expected at least one section"

    assert tree == initial_tree

    first_child = tree["children"][0]
    assert first_child["depth"] == 0
    assert first_child["title"]
    span = first_child["span"]
    if span["start_object"] is not None:
        ids = {item["object_id"] for item in objects_payload}
        assert span["start_object"] in ids
        assert span["end_object"] in ids

    order_map = {item["object_id"]: item["order_index"] for item in objects_payload}
    collected_spans = []
    for child in tree["children"]:
        child_span = child["span"]
        start_id = child_span["start_object"]
        end_id = child_span["end_object"]
        if start_id and end_id:
            collected_spans.append((order_map[start_id], order_map[end_id]))
            assert order_map[start_id] <= order_map[end_id]
    assert collected_spans == sorted(collected_spans, key=lambda pair: pair[0])

    persisted = client.get(f"/headers/{file_id}")
    assert persisted.status_code == 200
    assert persisted.json() == tree

    llama = client.post(f"/headers/{file_id}/find", params={"llm": "llamacpp"})
    assert llama.status_code == 200
    llama_tree = llama.json()
    assert llama_tree["children"]

    persisted_again = client.get(f"/headers/{file_id}")
    assert persisted_again.status_code == 200
    assert persisted_again.json() == llama_tree
