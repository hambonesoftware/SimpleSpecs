"""Test configuration for SimpleSpecs."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Generator

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import reset_settings_cache  # noqa: E402
from backend.database import reset_database_state  # noqa: E402
from backend.llm_client import LLMClient, LLMRequest  # noqa: E402
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
    monkeypatch.setenv("SPECS_DB_URL", f"sqlite:///{tmp_path / 'specs.db'}")
    monkeypatch.setenv("SPECS_PRIMARY_MODEL", "mock-primary")
    monkeypatch.setenv("SPECS_FALLBACK_MODEL", "mock-fallback")
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


class MockLLM(LLMClient):
    """Mock LLM client with a simple FIFO response queue."""

    def __init__(self) -> None:
        super().__init__(transport=self._dispatch)
        self._queue: list[str | Exception] = []
        self.requests: list[LLMRequest] = []

    def enqueue(self, response: str | Exception) -> None:
        self._queue.append(response)

    async def _dispatch(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if not self._queue:
            raise RuntimeError("MockLLM was called without a queued response")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def sample_text_simple() -> str:
    path = Path("tests/fixtures/sample_text_simple.txt")
    return path.read_text()


@pytest.fixture
def sample_text_normative() -> str:
    path = Path("tests/fixtures/sample_text_normative.txt")
    return path.read_text()


def pytest_pyfunc_call(pyfuncitem):
    if asyncio.iscoroutinefunction(pyfuncitem.obj):
        loop = asyncio.new_event_loop()
        try:
            signature = inspect.signature(pyfuncitem.obj)
            kwargs = {
                name: pyfuncitem.funcargs[name]
                for name in signature.parameters
                if name in pyfuncitem.funcargs
            }
            loop.run_until_complete(pyfuncitem.obj(**kwargs))
        finally:
            loop.close()
        return True
    return None
