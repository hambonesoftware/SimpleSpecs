"""Unit tests for OpenRouter client helpers."""

from __future__ import annotations

import importlib
import types

import pytest


@pytest.fixture(autouse=True)
def reload_client(monkeypatch):
    """Ensure the client module is reloaded with a clean environment."""

    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setitem(
        importlib.import_module("sys").modules,
        "requests",
        types.SimpleNamespace(post=None),
    )
    module = importlib.import_module("backend.services.openrouter_client")
    yield module


def test_merge_payload_prefers_env_model(monkeypatch, reload_client):
    """The OPENROUTER_MODEL env var should override other defaults."""

    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/custom-model")
    client = importlib.reload(reload_client)

    payload = client._merge_payload(  # type: ignore[attr-defined]
        messages=[{"role": "user", "content": "ping"}],
        model=None,
        temperature=0.5,
        params={},
    )

    assert payload["model"] == "openrouter/custom-model"


def test_merge_payload_uses_settings_when_env_missing(monkeypatch, reload_client):
    """If the env var is absent, fall back to the configured settings."""

    class DummySettings:
        openrouter_model = "openrouter/from-settings"

    client = importlib.reload(reload_client)
    monkeypatch.setattr(client, "get_settings", lambda: DummySettings(), raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    payload = client._merge_payload(  # type: ignore[attr-defined]
        messages=[{"role": "user", "content": "ping"}],
        model=None,
        temperature=0.5,
        params={},
    )

    assert payload["model"] == "openrouter/from-settings"
