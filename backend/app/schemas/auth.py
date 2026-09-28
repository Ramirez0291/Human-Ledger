from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SetupRequest(BaseModel):
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
    needs_setup: bool
    authenticated: bool
    allow_registration: bool = True
    user: UserOut | None = None
    default_locale: str
    supported_locales: list[str]
    app_name: str
    version: str
