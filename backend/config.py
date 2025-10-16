"""Application configuration module for SimpleSpecs."""

from functools import lru_cache
from typing import Annotated, Any, Dict, List, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources.types import NoDecode


class Settings(BaseSettings):
    """Runtime settings loaded from the environment."""

    model_config = SettingsConfigDict(env_prefix="SIMPLS_", extra="ignore")

    OPENROUTER_API_KEY: str | None = Field(default=None)
    LLAMACPP_URL: str = Field(default="http://localhost:8080")
    DB_URL: str = Field(default="sqlite:///./simplespecs.db")
    ARTIFACTS_DIR: str = Field(default="artifacts")
    ALLOW_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
    )
    MAX_FILE_MB: int = Field(default=50, ge=1)
    PDF_ENGINE: Literal["native", "mineru", "auto"] = Field(default="native")
    MINERU_ENABLED: bool = Field(default=True)
    MINERU_MODEL_OPTS: Dict[str, Any] = Field(default_factory=dict)
    PARSER_MULTI_COLUMN: bool = Field(
        default=True,
        validation_alias=AliasChoices("PARSER_MULTI_COLUMN", "SIMPLS_PARSER_MULTI_COLUMN"),
    )
    HEADERS_SUPPRESS_TOC: bool = Field(
        default=True,
        validation_alias=AliasChoices("HEADERS_SUPPRESS_TOC", "SIMPLS_HEADERS_SUPPRESS_TOC"),
    )
    HEADERS_SUPPRESS_RUNNING: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "HEADERS_SUPPRESS_RUNNING",
            "SIMPLS_HEADERS_SUPPRESS_RUNNING",
        ),
    )
    PARSER_ENABLE_OCR: bool = Field(
        default=False,
        validation_alias=AliasChoices("PARSER_ENABLE_OCR", "SIMPLS_PARSER_ENABLE_OCR"),
    )
    PARSER_DEBUG: bool = Field(
        default=False,
        validation_alias=AliasChoices("PARSER_DEBUG", "SIMPLS_PARSER_DEBUG"),
    )
    RAG_ENABLE: bool = Field(default=True)
    RAG_CHUNK_MODE: Literal["section"] = Field(default="section")
    RAG_MODEL_PATH: str = Field(default="./models/all-MiniLM-L6-v2")
    RAG_INDEX_DIR: str = Field(default="./.rag_index")
    RAG_HYBRID_ALPHA: float = Field(default=0.5)
    RAG_LIGHT_MODE: int = Field(default=1, ge=0, le=1)

    @field_validator("RAG_CHUNK_MODE", mode="before")
    @classmethod
    def _enforce_section_chunk_mode(cls, value: Any) -> Literal["section"]:
        """Ensure that only section chunking is permitted for RAG."""

        if value != "section":
            raise ValueError(
                "RAG_CHUNK_MODE is hard-enforced to 'section' for Phase 2."
            )
        return "section"

    @field_validator("ALLOW_ORIGINS", mode="before")
    @classmethod
    def _ensure_list(cls, value: Any) -> List[str]:
        """Allow comma-separated strings or iterables for origins."""
        if value is None:
            return ["http://localhost:3000"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()
