from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_settings  # noqa: E402
from backend.main import create_app  # noqa: E402


def _hash_payload(payload: list[dict[str, object]]) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def test_resume_on_failure() -> None:
    """Spec extraction endpoints persist deterministic results across adapters."""

    original = os.environ.get("SIMPLS_ARTIFACTS_DIR")
    with tempfile.TemporaryDirectory() as tmp_dir:
        artifacts_dir = Path(tmp_dir) / "artifacts"
        os.environ["SIMPLS_ARTIFACTS_DIR"] = str(artifacts_dir)
        get_settings.cache_clear()
        client = TestClient(create_app())

        content = (
            "1. Introduction\n"
            "Overview of the system.\n"
            "1.1 Background\n"
            "- The actuator shall withstand 500 N axial load.\n"
            "2. Methods\n"
            "- Operating temperature range 0 to 60 °C.\n"
            "3. Results\n"
            "Materials shall comply with ISO 2768.\n"
        ).encode("utf-8")

        ingest = client.post(
            "/ingest",
            files={"file": ("specs.txt", BytesIO(content), "text/plain")},
        )
        assert ingest.status_code == 200
        file_id = ingest.json()["file_id"]

        headers = client.post(f"/headers/{file_id}/find")
        assert headers.status_code == 200

        chunk_response = client.post(f"/chunks/{file_id}")
        assert chunk_response.status_code == 200
        chunk_map = chunk_response.json()

        first = client.post(f"/specs/{file_id}/find", params={"llm": "openrouter"})
        assert first.status_code == 200
        first_specs = first.json()
        assert isinstance(first_specs, list)
        assert first_specs

        repeat = client.post(f"/specs/{file_id}/find", params={"llm": "openrouter"})
        assert repeat.status_code == 200
        second_specs = repeat.json()
        assert _hash_payload(second_specs) == _hash_payload(first_specs)

        llama = client.post(f"/specs/{file_id}/find", params={"llm": "llamacpp"})
        assert llama.status_code == 200
        llama_specs = llama.json()
        assert llama_specs == first_specs

        persisted = client.get(f"/specs/{file_id}")
        assert persisted.status_code == 200
        assert persisted.json() == first_specs

        expected_keys = {
            "spec_id",
            "file_id",
            "section_id",
            "section_number",
            "section_title",
            "spec_text",
            "confidence",
            "source_object_ids",
        }
        for item in first_specs:
            assert expected_keys.issubset(item.keys())
            assert item["source_object_ids"] == chunk_map[item["section_id"]]
            assert item["file_id"] == file_id
            assert item["spec_text"].strip() == item["spec_text"]
    if original is None:
        os.environ.pop("SIMPLS_ARTIFACTS_DIR", None)
    else:
        os.environ["SIMPLS_ARTIFACTS_DIR"] = original
    get_settings.cache_clear()
