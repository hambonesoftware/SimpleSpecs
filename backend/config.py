"""Configuration utilities for the SimpleSpecs backend."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


def _env_flag(name: str, default: bool) -> bool:
    """Return a boolean flag derived from environment variables."""

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_TERMS_DIR = BASE_DIR / "resources" / "terms"
DEFAULT_BASELINES_PATH = BASE_DIR / "resources" / "baselines" / "mandatory_clauses.json"


HEADERS_TRACE: bool = os.getenv("HEADERS_TRACE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
HEADERS_TRACE_EMBED_RESPONSE: bool = (
    os.getenv("HEADERS_TRACE_EMBED_RESPONSE", "0").strip().lower()
    in {"1", "true", "yes", "on"}
)
HEADERS_TRACE_DIR: str = os.getenv("HEADERS_TRACE_DIR", "backend/logs/headers")
HEADERS_LOG_LEVEL: str = os.getenv("HEADERS_LOG_LEVEL", "DEBUG")


def _load_environment() -> None:
    """Load environment variables from a ``.env`` file if present."""

    explicit_path = os.getenv("SIMPLESPECS_ENV_FILE")
    candidates = []

    if explicit_path:
        candidates.append(Path(explicit_path))

    candidates.append(PROJECT_ROOT / ".env")

    for candidate in candidates:
        try_path = candidate.expanduser()
        if try_path.exists():
            load_dotenv(try_path, override=False)


_load_environment()


def _database_url_default() -> str:
    """Return the configured database URL using legacy fallbacks."""

    return (
        os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "sqlite:///./simplespecs.db"
    )


def _cors_origin_regex_default() -> str | None:
    """Return the default CORS origin regex allowing local network hosts."""

    raw = os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|(?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?",
    )
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""

    database_url: str = Field(default_factory=_database_url_default)
    upload_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("UPLOAD_DIR", str(PROJECT_ROOT / "uploads"))
        )
    )
    max_upload_size: int = Field(
        default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE", str(25 * 1024 * 1024)))
    )
    allowed_mimetypes: Tuple[str, ...] = Field(
        default_factory=lambda: tuple(
            mime.strip()
            for mime in os.getenv("ALLOWED_MIMETYPES", "application/pdf").split(",")
            if mime.strip()
        )
    )
    cors_allow_origins: Tuple[str, ...] = Field(default_factory=tuple)
    cors_allow_origin_regex: str | None = Field(default_factory=_cors_origin_regex_default)
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "info"))
    parser_multi_column: bool = Field(
        default_factory=lambda: _env_flag("PARSER_MULTI_COLUMN", True)
    )
    parser_enable_ocr: bool = Field(
        default_factory=lambda: _env_flag("PARSER_ENABLE_OCR", False)
    )
    headers_suppress_toc: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_SUPPRESS_TOC", True)
    )
    headers_suppress_running: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_SUPPRESS_RUNNING", True)
    )
    headers_llm_strict: bool = Field(
        default_factory=lambda: os.getenv("HEADERS_LLM_STRICT", "false").lower()
        == "true"
    )
    headers_mode: str = Field(
        default_factory=lambda: os.getenv("HEADERS_MODE", "llm_full")
    )
    headers_llm_model: str = Field(
        default_factory=lambda: os.getenv(
            "HEADERS_LLM_MODEL", "anthropic/claude-3.5-sonnet"
        )
    )
    headers_llm_max_input_tokens: int = Field(
        default_factory=lambda: int(
            os.getenv("HEADERS_LLM_MAX_INPUT_TOKENS", "120000")
        )
    )
    headers_llm_timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_LLM_TIMEOUT_S", "120"))
    )
    headers_llm_cache_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("HEADERS_LLM_CACHE_DIR", "./.cache/headers")
        )
    )
    mineru_fallback: bool = Field(
        default_factory=lambda: _env_flag("MINERU_FALLBACK", False)
    )
    llm_provider: str = Field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter")
    )
    openrouter_api_key: str | None = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    openrouter_model: str = Field(
        default_factory=lambda: os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    )
    openrouter_http_referer: str | None = Field(
        default_factory=lambda: os.getenv("OPENROUTER_SITE_URL")
        or os.getenv("HTTP_REFERER")
    )
    openrouter_title: str | None = Field(
        default_factory=lambda: os.getenv("OPENROUTER_X_TITLE")
        or os.getenv("X_TITLE")
    )
    spec_terms_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("SPEC_TERMS_DIR", str(DEFAULT_TERMS_DIR))
        )
    )
    spec_rule_min_hits: int = Field(
        default_factory=lambda: int(os.getenv("SPEC_RULE_MIN_HITS", "1"))
    )
    spec_multi_label_margin: float = Field(
        default_factory=lambda: float(os.getenv("SPEC_MULTI_LABEL_MARGIN", "0.0"))
    )
    risk_baselines_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("RISK_BASELINES_PATH", str(DEFAULT_BASELINES_PATH))
        )
    )
    export_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("EXPORT_DIR", str(PROJECT_ROOT / "exports"))
        )
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

    @field_validator("headers_llm_cache_dir", mode="after")
    @classmethod
    def _ensure_headers_cache_dir(cls, value: Path) -> Path:
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
