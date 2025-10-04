from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app
from backend.database import init_db, get_engine
from sqlalchemy import inspect
from backend.constants import MAX_TOKENS_LIMIT


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    db_path = tmp_path / "settings.db"
    monkeypatch.setenv("SIMPLS_DB_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_model_settings_persist_between_requests(monkeypatch, tmp_path):
    client = _create_client(monkeypatch, tmp_path)

    init_db()
    inspector = inspect(get_engine())
    assert "modelsettings" in inspector.get_table_names()

    initial = client.get("/api/settings")
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["provider"] == "openrouter"
    assert payload["max_tokens"] == MAX_TOKENS_LIMIT
    assert "updated_at" in payload

    update_payload = {
        "provider": "llamacpp",
        "model": "llama-model",
        "temperature": 0.6,
        "max_tokens": MAX_TOKENS_LIMIT,
        "api_key": "",
        "base_url": "http://localhost:9000",
    }
    updated = client.put("/api/settings", json=update_payload)
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["provider"] == "llamacpp"
    assert updated_payload["model"] == "llama-model"
    assert updated_payload["base_url"] == "http://localhost:9000"

    persisted = client.get("/api/settings")
    assert persisted.status_code == 200
    persisted_payload = persisted.json()
    assert persisted_payload["provider"] == "llamacpp"
    assert persisted_payload["model"] == "llama-model"
    assert persisted_payload["temperature"] == 0.6
    assert persisted_payload["max_tokens"] == MAX_TOKENS_LIMIT
    assert persisted_payload["base_url"] == "http://localhost:9000"
