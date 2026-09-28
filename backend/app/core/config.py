"""Settings, overridable via environment variables or .env."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Human Ledger"
    app_env: str = Field(default="development")  # development | production
    debug: bool = Field(default=True)

    secret_key: str = Field(default="")
    session_cookie_name: str = "human_ledger_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30
    cookie_secure: bool = Field(default=False)

    allow_registration: bool = Field(default=True)

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    database_url: str = Field(default="")

    default_locale: str = Field(default="zh-CN")
    timezone: str = Field(default="Asia/Tokyo")

    # none | local | cloud_llm
    ocr_provider: str = Field(default="none")
    ocr_api_key: str = Field(default="")
    ocr_api_base: str = Field(default="")
    ocr_model: str = Field(default="")

    @field_validator("data_dir", mode="after")
    @classmethod
    def _ensure_data_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        (v / "uploads").mkdir(parents=True, exist_ok=True)
        return v

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'ledger.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.secret_key:
        if s.is_production:
            raise RuntimeError(
                "SECRET_KEY must be set in production."
            )
        s.secret_key = secrets.token_urlsafe(48)
    return s


settings = get_settings()
