"""Tests for OpenRouter header utilities."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, status

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.openrouter import normalize_openrouter_base_url


def test_normalize_base_url_defaults_to_openrouter() -> None:
    assert (
        normalize_openrouter_base_url(None)
        == "https://openrouter.ai/api/v1"
    )
    assert (
        normalize_openrouter_base_url("  \t")
        == "https://openrouter.ai/api/v1"
    )


def test_normalize_base_url_adds_scheme_when_missing() -> None:
    assert (
        normalize_openrouter_base_url("openrouter.ai/api/v1")
        == "https://openrouter.ai/api/v1"
    )


def test_normalize_base_url_upgrades_http_scheme() -> None:
    assert (
        normalize_openrouter_base_url("http://openrouter.ai/api/v1")
        == "https://openrouter.ai/api/v1"
    )


def test_normalize_base_url_rejects_invalid_value() -> None:
    with pytest.raises(HTTPException) as exc_info:
        normalize_openrouter_base_url("http://")

    error = exc_info.value
    assert error.status_code == status.HTTP_400_BAD_REQUEST
    assert "base_url" in error.detail
