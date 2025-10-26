"""Tests for startup behaviour defined in ``backend.main``."""

from __future__ import annotations

import importlib
import sys


def _reload(module_name: str):
    """Import and reload the requested module."""

    module = sys.modules.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
    return importlib.reload(module)


def test_startup_logs_openrouter_api_key(monkeypatch, tmp_path, caplog):
    """The backend should announce the OpenRouter API key status at startup."""

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=sk-test-secret\n", encoding="utf-8")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SIMPLESPECS_ENV_FILE", str(env_file))

    _reload("backend.config")

    caplog.clear()
    with caplog.at_level("INFO", logger="uvicorn.error"):
        main_module = _reload("backend.main")

    messages = [
        record.message
        for record in caplog.records
        if "OpenRouter API key" in record.message
    ]

    assert messages, "Expected a startup log message confirming the API key status."

    expected_mask = main_module._mask_api_key("sk-test-secret")

    assert any(expected_mask in message for message in messages)
    assert all("sk-test-secret" not in message for message in messages)
