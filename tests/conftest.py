"""Test configuration for SimpleSpecs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.config import reset_settings_cache  # noqa: E402
from backend.database import reset_database_state  # noqa: E402
from backend.observability import metrics_registry  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    """Provide isolated configuration for each test."""

    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("EXPORT_RETENTION_DAYS", "1")
    monkeypatch.setenv("MAX_UPLOAD_SIZE", str(1024))
    reset_settings_cache()
    reset_database_state()
    metrics_registry.reset()
    yield
    reset_settings_cache()
    reset_database_state()
    metrics_registry.reset()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a test client for the FastAPI application."""

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
