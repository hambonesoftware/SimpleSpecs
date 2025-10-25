"""Configuration utilities for the SimpleSpecs backend."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from pydantic import BaseModel, Field, field_validator


def _env_flag(name: str, default: bool) -> bool:
    """Return a boolean flag derived from environment variables."""

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""

    database_url: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./simplespecs.db"))
    upload_dir: Path = Field(default_factory=lambda: Path(os.getenv("UPLOAD_DIR", "upload_objects_path")))
    max_upload_size: int = Field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE", str(25 * 1024 * 1024))))
    allowed_mimetypes: Tuple[str, ...] = Field(
        default_factory=lambda: tuple(
            mime.strip()
            for mime in os.getenv("ALLOWED_MIMETYPES", "application/pdf").split(",")
            if mime.strip()
        )
    )
    parser_multi_column: bool = Field(default_factory=lambda: _env_flag("PARSER_MULTI_COLUMN", True))
    parser_enable_ocr: bool = Field(default_factory=lambda: _env_flag("PARSER_ENABLE_OCR", False))
    headers_suppress_toc: bool = Field(default_factory=lambda: _env_flag("HEADERS_SUPPRESS_TOC", True))
    headers_suppress_running: bool = Field(default_factory=lambda: _env_flag("HEADERS_SUPPRESS_RUNNING", True))
    mineru_fallback: bool = Field(default_factory=lambda: _env_flag("MINERU_FALLBACK", False))

    @field_validator("upload_dir", mode="after")
    @classmethod
    def _ensure_upload_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("allowed_mimetypes", mode="after")
    @classmethod
    def _normalise_mimetypes(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        if not value:
            return ("application/pdf",)
        return tuple(dict.fromkeys(item.lower() for item in value))


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings so that subsequent calls reload from the environment."""

    get_settings.cache_clear()
