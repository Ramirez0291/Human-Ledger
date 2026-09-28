"""应用配置。

所有配置项均可通过环境变量或项目根目录的 .env 覆盖，前缀无。
参见 .env.example。
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 基础 ----
    app_name: str = "人类账本"
    app_env: str = Field(default="development")  # development | production
    debug: bool = Field(default=True)

    # ---- 安全 ----
    # 生产环境必须显式设置；未设置时每次启动随机生成（会导致会话失效）
    secret_key: str = Field(default="")
    session_cookie_name: str = "renlei_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 天
    # 通过 HTTPS 部署时应设为 true
    cookie_secure: bool = Field(default=False)

    # ---- 多用户 ----
    # 是否允许新用户自助注册。个人部署可关掉，只保留首次初始化创建的那个用户
    allow_registration: bool = Field(default=True)

    # ---- 数据 ----
    # 数据目录：SQLite 文件与上传的截图都放这里，部署时挂载为卷
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    database_url: str = Field(default="")

    # ---- 本地化 ----
    default_locale: str = Field(default="zh-CN")
    timezone: str = Field(default="Asia/Tokyo")

    # ---- OCR（预留，尚未接入）----
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
                "生产环境必须设置 SECRET_KEY 环境变量，否则每次重启都会导致所有会话失效。"
            )
        # 开发环境：允许自动生成，但重启后需要重新登录
        s.secret_key = secrets.token_urlsafe(48)
    return s


settings = get_settings()
