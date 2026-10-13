from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.regions import get_region


class SetupRequest(BaseModel):
    """首次启动时创建唯一用户。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    locale: str = Field(default="zh-CN", max_length=16)
    # 地区包键（JP / CN）；不给则用实例的 DEFAULT_REGION。建好后不可改
    region: str | None = Field(default=None, max_length=8)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    locale: str
    is_owner: bool = False
    region: str = "JP"

    # 前端按这两项格式化与解析金额：API 里的金额都是最小单位的整数
    @computed_field  # type: ignore[prop-decorator]
    @property
    def currency(self) -> str:
        return get_region(self.region).currency

    @computed_field  # type: ignore[prop-decorator]
    @property
    def minor_unit(self) -> int:
        return get_region(self.region).minor_unit


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
    default_region: str = "JP"
    supported_regions: list[str] = ["JP"]
    app_name: str
    version: str
