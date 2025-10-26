"""Tests for backend configuration helpers."""

from __future__ import annotations

import re

import importlib

import backend.config as config


def test_default_cors_regex_allows_local_network(monkeypatch):
    """The default regex should allow localhost and local-network origins."""

    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    settings = config.Settings()

    assert (
        settings.cors_allow_origin_regex
        == r"http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|(?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?"
    )


def test_default_cors_regex_matches_private_ipv4_origin(monkeypatch):
    """The default regex should match private IPv4 origins with custom ports."""

    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    settings = config.Settings()

    pattern = re.compile(settings.cors_allow_origin_regex)

    assert pattern.fullmatch("http://192.168.68.136:3600")


def test_blank_cors_regex_disables_pattern(monkeypatch):
    """Blank regex env vars should be treated as disabled (None)."""

    monkeypatch.setenv("CORS_ALLOW_ORIGIN_REGEX", "   ")
    settings = config.Settings()

    assert settings.cors_allow_origin_regex is None


def test_openrouter_api_key_loaded_from_env_file(monkeypatch, tmp_path):
    """The OPENROUTER_API_KEY should be sourced from a .env file when present."""

    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=file-value\n", encoding="utf-8")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SIMPLESPECS_ENV_FILE", str(env_file))

    module = importlib.reload(config)

    settings = module.Settings()

    assert settings.openrouter_api_key == "file-value"

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
