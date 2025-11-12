"""Configuration utilities for the SimpleSpecs backend."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - fallback for testing environments
    class BaseSettings(BaseModel):  # type: ignore[misc]
        """Fallback BaseSettings implementation when pydantic-settings is unavailable."""

        class Config:
            env_file = None


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


def _parse_weights(raw: str | None) -> tuple[float, ...]:
    """Return a tuple of floats parsed from a comma-delimited string."""

    if not raw:
        return (0.55, 0.30, 0.10, 0.05)
    parts: list[float] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parts.append(float(chunk))
        except ValueError:
            continue
    return tuple(parts) if parts else (0.55, 0.30, 0.10, 0.05)


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    """Return a tuple of non-empty strings parsed from ``raw``."""

    if raw is None:
        return ()
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(items)


def _default_spec_agents() -> tuple[str, ...]:
    """Return the configured spec agents or a Mechanical-only default."""

    parsed = _parse_csv(os.getenv("SPECS_ENABLED_AGENTS", "Mechanical"))
    return parsed or ("Mechanical",)

HEADERS_ALIGN_STRATEGY: str = os.getenv("HEADERS_ALIGN_STRATEGY", "sequential")
HEADERS_SUPPRESS_TOC: bool = os.getenv("HEADERS_SUPPRESS_TOC", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_SUPPRESS_RUNNING: bool = os.getenv("HEADERS_SUPPRESS_RUNNING", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_NORMALIZE_CONFUSABLES: bool = os.getenv(
    "HEADERS_NORMALIZE_CONFUSABLES", "1"
) in ("1", "true", "True", "YES", "yes")
HEADERS_FUZZY_THRESHOLD: int = int(os.getenv("HEADERS_FUZZY_THRESHOLD", "80"))
HEADERS_WINDOW_PAD_LINES: int = int(os.getenv("HEADERS_WINDOW_PAD_LINES", "40"))
HEADERS_BAND_LINES: int = int(os.getenv("HEADERS_BAND_LINES", "5"))
HEADERS_FUZZY_TITLE: int = int(os.getenv("HEADERS_FUZZY_TITLE", "80"))
HEADERS_FUZZY_TITLE_ONLY: int = int(os.getenv("HEADERS_FUZZY_TITLE_ONLY", "78"))
HEADERS_FUZZY_NUMTITLE: int = int(os.getenv("HEADERS_FUZZY_NUMTITLE", "82"))
HEADERS_L1_REQUIRE_NUMERIC: bool = os.getenv("HEADERS_L1_REQUIRE_NUMERIC", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_L1_LOOKAHEAD_CHILD_HINT: int = int(
    os.getenv("HEADERS_L1_LOOKAHEAD_CHILD_HINT", "30")
)
HEADERS_MONOTONIC_STRICT: bool = os.getenv("HEADERS_MONOTONIC_STRICT", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_REANCHOR_PASS: bool = os.getenv("HEADERS_REANCHOR_PASS", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_AFTER_ANCHOR_ONLY: bool = _env_flag("HEADERS_AFTER_ANCHOR_ONLY", True)
HEADERS_LAST_OCCURRENCE_FALLBACK: bool = _env_flag("HEADERS_LAST_OCCURRENCE_FALLBACK", True)
HEADERS_PENALTY_BAND: float = float(os.getenv("HEADERS_PENALTY_BAND", "0.25"))
HEADERS_PENALTY_TOC: float = float(os.getenv("HEADERS_PENALTY_TOC", "0.45"))
HEADERS_RUNNER_MIN_PAGES: int = int(os.getenv("HEADERS_RUNNER_MIN_PAGES", "2"))
HEADERS_STRICT_INVARIANTS: bool = os.getenv("HEADERS_STRICT_INVARIANTS", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_TITLE_ONLY_REANCHOR: bool = os.getenv("HEADERS_TITLE_ONLY_REANCHOR", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
HEADERS_RESCAN_PASSES: int = int(os.getenv("HEADERS_RESCAN_PASSES", "2"))
HEADERS_DEDUPE_POLICY: str = os.getenv("HEADERS_DEDUPE_POLICY", "best")

HEADER_LOCATE_USE_EMBEDDINGS: bool = _env_flag("HEADER_LOCATE_USE_EMBEDDINGS", False)
HEADER_LOCATE_FUSE_WEIGHTS: tuple[float, ...] = _parse_weights(
    os.getenv("HEADER_LOCATE_FUSE_WEIGHTS")
)
HEADER_LOCATE_MIN_LEXICAL: float = float(os.getenv("HEADER_LOCATE_MIN_LEXICAL", "0.3"))
HEADER_LOCATE_MIN_COSINE: float = float(os.getenv("HEADER_LOCATE_MIN_COSINE", "0.25"))
HEADER_LOCATE_PREFER_LAST_MATCH: bool = _env_flag(
    "HEADER_LOCATE_PREFER_LAST_MATCH", True
)

EMBEDDINGS_PROVIDER: str = os.getenv("EMBEDDINGS_PROVIDER", "local")
EMBEDDINGS_MODEL: str = os.getenv(
    "EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDINGS_CACHE_DIR: Path = Path(os.getenv("EMBEDDINGS_CACHE_DIR", ".cache/emb"))
EMBEDDINGS_OPENROUTER_MODEL: str = os.getenv(
    "EMBEDDINGS_OPENROUTER_MODEL", "openai/text-embedding-3-small"
)
EMBEDDINGS_OPENROUTER_TIMEOUT_S: int = int(
    os.getenv("EMBEDDINGS_OPENROUTER_TIMEOUT_S", "60")
)

# Strict/LLM matcher hardening
HEADERS_STRICT_FUZZY_THRESH: int = int(
    os.getenv("HEADERS_STRICT_FUZZY_THRESH", "75")
)
HEADERS_STRICT_TITLE_ONLY_THRESH: int = int(
    os.getenv("HEADERS_STRICT_TITLE_ONLY_THRESH", "72")
)
HEADERS_STRICT_BAND_LINES: int = int(
    os.getenv("HEADERS_STRICT_BAND_LINES", "3")
)
HEADERS_STRICT_TOC_MIN_SECTION_TOKENS: int = int(
    os.getenv("HEADERS_STRICT_TOC_MIN_SECTION_TOKENS", "6")
)
HEADERS_STRICT_TOC_MIN_DOT_LEADERS: int = int(
    os.getenv("HEADERS_STRICT_TOC_MIN_DOT_LEADERS", "4")
)
HEADERS_STRICT_AFTER_ANCHOR_ONLY: bool = os.getenv(
    "HEADERS_STRICT_AFTER_ANCHOR_ONLY", "1"
) in ("1", "true", "True", "YES", "yes")
HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK: bool = os.getenv(
    "HEADERS_STRICT_LAST_OCCURRENCE_FALLBACK", "1"
) in ("1", "true", "True", "YES", "yes")
HEADERS_FINAL_MONOTONIC_GUARD: bool = os.getenv(
    "HEADERS_FINAL_MONOTONIC_GUARD", "1"
) in ("1", "true", "True", "YES", "yes")
HEADERS_TOC_MIN_SECTION_TOKENS: int = int(
    os.getenv("HEADERS_TOC_MIN_SECTION_TOKENS", "6")
)
HEADERS_TOC_MIN_DOT_LEADERS: int = int(
    os.getenv("HEADERS_TOC_MIN_DOT_LEADERS", "4")
)
HEADERS_W_FUZZY: float = float(os.getenv("HEADERS_W_FUZZY", "0.6"))
HEADERS_W_POS: float = float(os.getenv("HEADERS_W_POS", "0.25"))
HEADERS_W_TYPO: float = float(os.getenv("HEADERS_W_TYPO", "0.15"))

# Extractor selection
PARSER_ENGINE: str = os.getenv("PARSER_ENGINE", "auto")

# Heuristics for "auto" page-level fallback
PARSER_NOISE_SPACED_DOT_THRESH: float = float(
    os.getenv("PARSER_NOISE_SPACED_DOT_THRESH", "0.18")
)
PARSER_NOISE_CONFUSABLE_1_THRESH: float = float(
    os.getenv("PARSER_NOISE_CONFUSABLE_1_THRESH", "0.12")
)

# Reading-order grouping
PARSER_LINE_Y_TOLERANCE: float = float(
    os.getenv("PARSER_LINE_Y_TOLERANCE", "2.0")
)

# Safety toggles
PARSER_KEEP_BBOX: bool = os.getenv("PARSER_KEEP_BBOX", "1") in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)


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
    specs_db_url: str = Field(
        default_factory=lambda: os.getenv("SPECS_DB_URL", "sqlite:////tmp/simplespecs.db")
    )
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
    headers_cache_to_db: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_CACHE_TO_DB", True)
    )
    headers_align_strategy: str = Field(
        default_factory=lambda: os.getenv("HEADERS_ALIGN_STRATEGY", "sequential")
    )
    headers_normalize_confusables: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_NORMALIZE_CONFUSABLES", True)
    )
    headers_fuzzy_threshold: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_FUZZY_THRESHOLD", "80"))
    )
    headers_window_pad_lines: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_WINDOW_PAD_LINES", "40"))
    )
    headers_band_lines: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_BAND_LINES", "5"))
    )
    headers_l1_require_numeric: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_L1_REQUIRE_NUMERIC", True)
    )
    headers_l1_lookahead_child_hint: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_L1_LOOKAHEAD_CHILD_HINT", "30"))
    )
    headers_monotonic_strict: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_MONOTONIC_STRICT", True)
    )
    headers_reanchor_pass: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_REANCHOR_PASS", True)
    )
    headers_strict_invariants: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_STRICT_INVARIANTS", True)
    )
    headers_title_only_reanchor: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_TITLE_ONLY_REANCHOR", True)
    )


    headers_rescan_passes: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_RESCAN_PASSES", "2"))
    )
    headers_dedupe_policy: str = Field(
        default_factory=lambda: os.getenv("HEADERS_DEDUPE_POLICY", "best")
    )
    headers_trace: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_TRACE", False)
    )
    headers_llm_strict: bool = Field(
        default_factory=lambda: _env_flag("HEADERS_LLM_STRICT", False)
    )
    headers_mode: str = Field(
        default_factory=lambda: os.getenv("HEADERS_MODE", "llm_simple")
    )
    headers_llm_model: str = Field(
        default_factory=lambda: os.getenv(
            "HEADERS_LLM_MODEL", "anthropic/claude-3.5-sonnet"
        )
    )
    headers_llm_model_fallback: str = Field(
        default_factory=lambda: os.getenv(
            "HEADERS_LLM_MODEL_FALLBACK",
            os.getenv("HEADERS_LLM_MODEL", "anthropic/claude-3.5-sonnet"),
        )
    )
    headers_llm_max_input_tokens: int = Field(
        default_factory=lambda: int(
            os.getenv("HEADERS_LLM_MAX_INPUT_TOKENS", "80000")
        )
    )
    headers_llm_timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_LLM_TIMEOUT_S", "240"))
    )
    headers_llm_cache_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("HEADERS_LLM_CACHE_DIR", ".cache/headers")
        )
    )
    headers_llm_chunking: str = Field(
        default_factory=lambda: os.getenv("HEADERS_LLM_CHUNKING", "auto")
    )
    headers_llm_chunk_target_tokens: int = Field(
        default_factory=lambda: int(
            os.getenv("HEADERS_LLM_CHUNK_TARGET_TOKENS", "35000")
        )
    )
    headers_llm_retry_max: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_LLM_RETRY_MAX", "3"))
    )
    headers_llm_backoff_s: float = Field(
        default_factory=lambda: float(os.getenv("HEADERS_LLM_BACKOFF_S", "2"))
    )
    headers_log_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("HEADERS_LOG_DIR", "backend/logs")
        )
    )
    headers_match_page_band: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_MATCH_PAGE_BAND", "2"))
    )
    headers_match_min_title_len: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_MATCH_MIN_TITLE_LEN", "4"))
    )
    headers_match_enable_offset_calibration: bool = Field(
        default_factory=lambda: _env_flag(
            "HEADERS_MATCH_ENABLE_OFFSET_CALIBRATION", True
        )
    )
    headers_match_offset_seed_min: int = Field(
        default_factory=lambda: int(os.getenv("HEADERS_MATCH_OFFSET_SEED_MIN", "3"))
    )
    header_locate_use_embeddings: bool = Field(
        default_factory=lambda: _env_flag("HEADER_LOCATE_USE_EMBEDDINGS", False)
    )
    header_locate_fuse_weights: Tuple[float, float, float, float] = Field(
        default_factory=lambda: tuple(
            HEADER_LOCATE_FUSE_WEIGHTS[:4]
            if len(HEADER_LOCATE_FUSE_WEIGHTS) >= 4
            else (0.55, 0.30, 0.10, 0.05)
        )
    )
    header_locate_min_lexical: float = Field(
        default_factory=lambda: float(os.getenv("HEADER_LOCATE_MIN_LEXICAL", "0.3"))
    )
    header_locate_min_cosine: float = Field(
        default_factory=lambda: float(os.getenv("HEADER_LOCATE_MIN_COSINE", "0.25"))
    )
    header_locate_prefer_last_match: bool = Field(
        default_factory=lambda: _env_flag("HEADER_LOCATE_PREFER_LAST_MATCH", True)
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
    embeddings_provider: str = Field(
        default_factory=lambda: os.getenv("EMBEDDINGS_PROVIDER", "local")
    )
    embeddings_model: str = Field(
        default_factory=lambda: os.getenv(
            "EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    embeddings_cache_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("EMBEDDINGS_CACHE_DIR", ".cache/emb")
        )
    )
    embeddings_openrouter_model: str = Field(
        default_factory=lambda: os.getenv(
            "EMBEDDINGS_OPENROUTER_MODEL", "openai/text-embedding-3-small"
        )
    )
    embeddings_openrouter_timeout_s: int = Field(
        default_factory=lambda: int(
            os.getenv("EMBEDDINGS_OPENROUTER_TIMEOUT_S", "60")
        )
    )
    specs_primary_model: str = Field(
        default_factory=lambda: os.getenv(
            "SPECS_PRIMARY_MODEL", "anthropic/claude-3.5-sonnet"
        )
    )
    specs_fallback_model: str | None = Field(
        default_factory=lambda: os.getenv("SPECS_FALLBACK_MODEL", "openai/gpt-4.1-mini")
    )
    specs_timeout_s: int = Field(
        default_factory=lambda: int(os.getenv("SPECS_TIMEOUT_S", "120"))
    )
    specs_retry_max: int = Field(
        default_factory=lambda: int(os.getenv("SPECS_RETRY_MAX", "1"))
    )
    specs_backoff_s: float = Field(
        default_factory=lambda: float(os.getenv("SPECS_BACKOFF_S", "1.5"))
    )
    specs_max_headers: int = Field(
        default_factory=lambda: int(os.getenv("SPECS_MAX_HEADERS", "10"))
    )
    specs_enabled_agents: Tuple[str, ...] = Field(
        default_factory=_default_spec_agents
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

    @field_validator("headers_log_dir", mode="after")
    @classmethod
    def _ensure_headers_log_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("header_locate_fuse_weights", mode="after")
    @classmethod
    def _normalise_fuse_weights(
        cls, value: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        weights = tuple(value)
        if len(weights) != 4:
            weights = (0.55, 0.30, 0.10, 0.05)
        total = sum(weights)
        if total <= 0:
            return (0.55, 0.30, 0.10, 0.05)
        return tuple(weight / total for weight in weights)

    @field_validator("header_locate_min_lexical", mode="after")
    @classmethod
    def _clamp_lexical(cls, value: float) -> float:
        return max(0.0, min(1.0, value))

    @field_validator("header_locate_min_cosine", mode="after")
    @classmethod
    def _clamp_cosine(cls, value: float) -> float:
        return max(0.0, min(1.0, value))

    @field_validator("headers_llm_chunking", mode="after")
    @classmethod
    def _normalise_chunking(cls, value: str) -> str:
        return (value or "auto").strip().lower() or "auto"

    @field_validator("headers_llm_chunk_target_tokens", mode="after")
    @classmethod
    def _clamp_chunk_target(cls, value: int) -> int:
        return max(1, int(value))

    @field_validator("headers_llm_retry_max", mode="after")
    @classmethod
    def _clamp_retry_max(cls, value: int) -> int:
        return max(0, int(value))

    @field_validator("headers_llm_backoff_s", mode="after")
    @classmethod
    def _clamp_backoff(cls, value: float) -> float:
        return max(0.0, float(value))

    @field_validator("headers_band_lines", mode="after")
    @classmethod
    def _clamp_band_lines(cls, value: int) -> int:
        return max(0, int(value))

    @field_validator("headers_l1_lookahead_child_hint", mode="after")
    @classmethod
    def _clamp_child_hint(cls, value: int) -> int:
        return max(0, int(value))

    @field_validator("headers_rescan_passes", mode="after")
    @classmethod
    def _clamp_rescan_passes(cls, value: int) -> int:
        return max(0, int(value))

    @field_validator("headers_align_strategy", mode="after")
    @classmethod
    def _normalise_align_strategy(cls, value: str) -> str:
        return (value or "sequential").strip().lower() or "sequential"

    @field_validator("headers_dedupe_policy", mode="after")
    @classmethod
    def _normalise_dedupe_policy(cls, value: str) -> str:
        return (value or "best").strip().lower() or "best"

    @field_validator("embeddings_cache_dir", mode="after")
    @classmethod
    def _ensure_embeddings_cache_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("export_retention_days", mode="after")
    @classmethod
    def _normalise_retention(cls, value: int) -> int:
        return max(0, value)

    @field_validator("specs_fallback_model", mode="after")
    @classmethod
    def _normalise_specs_fallback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings so that subsequent calls reload from the environment."""

    get_settings.cache_clear()


class SpecSearchSettings(BaseSettings):
    """Settings specific to the spec-search LLM pipeline."""

    PRIMARY_MODEL: str = "anthropic/claude-3.5-sonnet"
    FALLBACK_MODEL: str = "openai/gpt-4.1-mini"
    TIMEOUT_S: int = 240
    MAX_TOKENS: int = 80_000
    CHUNK_TARGET_TOKENS: int = 35_000
    RETRY_MAX: int = 4
    BACKOFF_S: float = 2.0


spec_search_settings = SpecSearchSettings()
