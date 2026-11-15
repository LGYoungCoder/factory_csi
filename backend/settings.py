"""Application settings from environment / .env (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM (LiteLLM)
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek/deepseek-flash"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str | None = None
    llm_thinking: bool = False
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_audit_text_max_chars: int = 20_000

    # app
    data_dir: Path = Path("data")
    app_db_path: Path = Path("var/app.db")
    checkpoint_db_path: Path = Path("var/checkpoints.db")
    log_dir: Path = Path("logs")
    cors_origins: str = "http://localhost:5173"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # investigation budgets
    case_max_mcp_calls: int = 20
    case_max_llm_calls: int = 40
    max_verification_rounds: int = 3
    max_reject_all: int = 2
    tool_loop_max_calls: int = 6
    evidence_payload_max_chars: int = 24_000

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def _empty_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must list explicit origins, '*' is not allowed")
        return v

    @property
    def effective_model(self) -> str:
        return self.llm_model if "/" in self.llm_model else f"{self.llm_provider}/{self.llm_model}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
