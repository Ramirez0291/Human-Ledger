"""「今天」按用户所在时区算，而不是服务器时区。

容器里的服务器通常跑 UTC：日本时间 9/1 早上 8 点，服务器还是 8/31——
预算会把整个月当成「已经过完」、报表默认打开上个月。所有「今天 / 本月」都从这里取。

有用户上下文时传入其地区包的时区（`region_of(user).timezone`）；不传则用实例配置 `TIMEZONE`。

zoneinfo 在 Windows 上要 tzdata 包才有时区数据（requirements 已列）；万一没有，
固定偏移的时区（日本、中国都没有夏令时）按偏移兜底，其余退回服务器本地日期。
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

from app.core.config import settings

_FIXED_OFFSETS = {"Asia/Tokyo": 9, "Asia/Seoul": 9, "Asia/Shanghai": 8, "Asia/Taipei": 8, "Asia/Hong_Kong": 8, "UTC": 0}


@lru_cache
def _tz(name: str) -> dt.tzinfo | None:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError / 缺 tzdata
        hours = _FIXED_OFFSETS.get(name)
        return dt.timezone(dt.timedelta(hours=hours)) if hours is not None else None


def local_now(tz: str | None = None) -> dt.datetime:
    zone = _tz(tz or settings.timezone)
    return dt.datetime.now(zone) if zone else dt.datetime.now()


def local_today(tz: str | None = None) -> dt.date:
    return local_now(tz).date()
