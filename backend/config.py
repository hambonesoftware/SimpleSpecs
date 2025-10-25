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


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TERMS_DIR = BASE_DIR / "resources" / "terms"
DEFAULT_BASELINES_PATH = BASE_DIR / "resources" / "baselines" / "mandatory_clauses.json"


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
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter"))
    openrouter_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    openrouter_model: str = Field(default_factory=lambda: os.getenv("OPENROUTER_MODEL", "openrouter/auto"))
    openrouter_http_referer: str | None = Field(default_factory=lambda: os.getenv("HTTP_REFERER"))
    openrouter_title: str | None = Field(default_factory=lambda: os.getenv("X_TITLE"))
    spec_terms_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("SPEC_TERMS_DIR", str(DEFAULT_TERMS_DIR)))
    )
    spec_rule_min_hits: int = Field(default_factory=lambda: int(os.getenv("SPEC_RULE_MIN_HITS", "1")))
    spec_multi_label_margin: float = Field(
        default_factory=lambda: float(os.getenv("SPEC_MULTI_LABEL_MARGIN", "0.0"))
    )
    risk_baselines_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("RISK_BASELINES_PATH", str(DEFAULT_BASELINES_PATH))
        )
    )
    export_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("EXPORT_DIR", "exported_reports"))
    )
    export_retention_days: int = Field(
        default_factory=lambda: int(os.getenv("EXPORT_RETENTION_DAYS", "30"))
    )

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

    @field_validator("spec_terms_dir", mode="after")
    @classmethod
    def _ensure_terms_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("risk_baselines_path", mode="after")
    @classmethod
    def _ensure_baseline_file(cls, value: Path) -> Path:
        value.parent.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("export_dir", mode="after")
    @classmethod
    def _ensure_export_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("export_retention_days", mode="after")
    @classmethod
    def _normalise_retention(cls, value: int) -> int:
        return max(0, value)


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings so that subsequent calls reload from the environment."""

    get_settings.cache_clear()
