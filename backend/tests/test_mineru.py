from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from backend.services.mineru_adapter import MinerUConfig, parse_with_mineru
from backend.services.pdf_mineru import mineru_blocks_to_parsed_objects

MINERU_AVAILABLE = importlib.util.find_spec("mineru") is not None

if not MINERU_AVAILABLE:
    pytestmark = pytest.mark.skip(reason="MinerU package not installed")


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    path = Path(__file__).parent / "data" / "sample.pdf"
    assert path.exists(), "tests/data/sample.pdf missing"
    return path.read_bytes()


def test_mineru_library_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_pdf_bytes: bytes) -> None:
    monkeypatch.setenv("MINERU_MODE", "library")
    monkeypatch.setenv("MINERU_OUT_ROOT", str(tmp_path))
    cfg = MinerUConfig()
    objects, out_dir = parse_with_mineru("ut_upload_1", sample_pdf_bytes, "sample.pdf", cfg)
    assert isinstance(objects, list)
    assert out_dir.exists()
    assert all(obj.get("source") == "mineru" for obj in objects)

    parsed = mineru_blocks_to_parsed_objects(objects, "ut_upload_1")
    assert all(obj.metadata.get("engine") == "mineru" for obj in parsed)


@pytest.mark.optional
def test_mineru_server_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_pdf_bytes: bytes) -> None:
    monkeypatch.setenv("MINERU_MODE", "server")
    monkeypatch.setenv("MINERU_SERVER_URL", os.getenv("MINERU_SERVER_URL", "http://127.0.0.1:8000"))
    monkeypatch.setenv("MINERU_OUT_ROOT", str(tmp_path))
    cfg = MinerUConfig()
    objects, out_dir = parse_with_mineru("ut_upload_2", sample_pdf_bytes, "sample.pdf", cfg)
    assert isinstance(objects, list)
    assert out_dir.exists()
