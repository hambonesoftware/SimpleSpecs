"""Tests for backend configuration helpers."""

from __future__ import annotations

from backend.config import Settings


def test_default_cors_regex_allows_local_network(monkeypatch):
    """The default regex should allow localhost and local-network origins."""

    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    settings = Settings()

    assert (
        settings.cors_allow_origin_regex
        == r"http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|(?:\d{1,3}\.){3}\d)(?::\d{1,5})?"
    )


def test_blank_cors_regex_disables_pattern(monkeypatch):
    """Blank regex env vars should be treated as disabled (None)."""

    monkeypatch.setenv("CORS_ALLOW_ORIGIN_REGEX", "   ")
    settings = Settings()

    assert settings.cors_allow_origin_regex is None
