from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.models import LINE_KIND, PARAGRAPH_KIND


client = TestClient(create_app())


def _assert_objects_shape(objects: list[dict[str, Any]]) -> None:
    assert isinstance(objects, list) and objects, "Expected parsed objects"
    required_keys = {"object_id", "file_id", "kind", "order_index", "metadata"}
    for obj in objects:
        assert required_keys.issubset(obj.keys())
        assert isinstance(obj["metadata"], dict)
    orders = [obj["order_index"] for obj in objects]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)
    ordering_keys = [((obj.get("page_index") or 0), obj["order_index"]) for obj in objects]
    assert ordering_keys == sorted(ordering_keys)


def _upload_txt(lines: list[str]) -> dict[str, Any]:
    content = "\n".join(lines).encode("utf-8")
    files = {"file": ("note.txt", BytesIO(content), "text/plain")}
    response = client.post("/ingest", files=files)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "file_id" in payload and "object_count" in payload
    return payload


def test_parse_txt_golden() -> None:
    payload = _upload_txt(["alpha", "beta", "gamma"])
    parsed = client.get(f"/parsed/{payload['file_id']}")
    assert parsed.status_code == 200, parsed.text
    objects = parsed.json()
    _assert_objects_shape(objects)
    texts = [
        obj.get("text")
        for obj in objects
        if obj["kind"] in {LINE_KIND, PARAGRAPH_KIND} and obj.get("text")
    ]
    assert any(
        text is not None and any(line in text for line in ("alpha", "beta", "gamma"))
        for text in texts
    )
