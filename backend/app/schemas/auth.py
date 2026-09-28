from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SetupRequest(BaseModel):
    """首次启动时创建唯一用户。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    locale: str = Field(default="zh-CN", max_length=16)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    locale: str


class LocaleUpdate(BaseModel):
    locale: str = Field(max_length=16)


class StatusOut(BaseModel):
    """前端启动时据此决定进入 初始化 / 登录 / 主界面。"""

    needs_setup: bool
    authenticated: bool
    # 是否显示「注册」入口
    allow_registration: bool = True
    user: UserOut | None = None
    default_locale: str
    supported_locales: list[str]
    app_name: str
    version: str
