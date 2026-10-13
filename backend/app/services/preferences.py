"""用户偏好（settings 表，按用户的键值）。

ledger_mode —— 记账风格：
  relaxed（默认）  个人账本会漏记，这很正常。余额以最近一次看到的真实余额为准，
                   信用卡最多还到 0、现金 / 电子钱包最少花到 0，不提示对账差额
  strict           余额严格等于期初 + 全部流水，差额提示漏记（适合要逐笔对得上的家庭）
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db.models import AppSetting

LEDGER_MODES = ("relaxed", "strict")
DEFAULTS: dict[str, object] = {"ledger_mode": "relaxed"}


def get_pref(db: Session, user_id: int, key: str):
    row = db.query(AppSetting).filter(AppSetting.user_id == user_id, AppSetting.key == key).first()
    if row is None:
        return DEFAULTS.get(key)
    try:
        return json.loads(row.value)
    except ValueError:
        return DEFAULTS.get(key)


def set_pref(db: Session, user_id: int, key: str, value) -> None:
    row = db.query(AppSetting).filter(AppSetting.user_id == user_id, AppSetting.key == key).first()
    if row is None:
        row = AppSetting(user_id=user_id, key=key, value="")
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)


def ledger_mode(db: Session, user_id: int) -> str:
    mode = get_pref(db, user_id, "ledger_mode")
    return mode if mode in LEDGER_MODES else "relaxed"
