"""Utilities for interacting with the OpenRouter API."""

from __future__ import annotations

import httpx
from fastapi import HTTPException, status

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def normalize_openrouter_base_url(raw_base_url: str | None) -> str:
    """Return a sanitized base URL for OpenRouter requests."""

    base_url = (raw_base_url or DEFAULT_OPENROUTER_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_OPENROUTER_BASE_URL

    if "://" not in base_url:
        base_url = f"https://{base_url}"

    try:
        parsed = httpx.URL(base_url)
    except httpx.InvalidURL as exc:  # pragma: no cover - input validation
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base_url: {exc}",
        ) from exc

    if not parsed.scheme or not parsed.host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url must include a hostname",
        )

    sanitized = parsed.copy_with(query=None, fragment=None)
    if sanitized.scheme == "http":
        sanitized = sanitized.copy_with(scheme="https")

    return str(sanitized)

