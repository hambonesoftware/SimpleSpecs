"""Application configuration module for SimpleSpecs."""
from functools import lru_cache
from typing import Any, Dict, List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the environment."""

    model_config = SettingsConfigDict(env_prefix="SIMPLS_", extra="ignore")

    OPENROUTER_API_KEY: str | None = Field(default=None)
    LLAMACPP_URL: str = Field(default="http://localhost:8080")
    DB_URL: str = Field(default="sqlite:///./simplespecs.db")
    ARTIFACTS_DIR: str = Field(default="artifacts")
    ALLOW_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])
    MAX_FILE_MB: int = Field(default=50, ge=1)
    PDF_ENGINE: Literal["native", "mineru", "auto"] = Field(default="native")
    MINERU_ENABLED: bool = Field(default=True)
    MINERU_MODEL_OPTS: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("ALLOW_ORIGINS", mode="before")
    @classmethod
    def _ensure_list(cls, value: Any) -> List[str]:
        """Allow comma-separated strings or iterables for origins."""
        if value is None:
            return ["*"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""

    return Settings()
