"""支付方式 → 账户（微信 / 支付宝这类跨账户账单用）。

账单里的「支付方式」是原文：「零钱」「招商银行信用卡(0575)」「中国银行储蓄卡(6721)」。
同一张卡在不同列里写法不一（提现那行的交易对方是「中国银行(6721)」），
所以先归一成键：**银行名 + 尾号**，卡种（信用卡 / 储蓄卡）只用于新建账户时定类型。

映射的来源，依次：
1. 用户上次确认过的映射（偏好 `payment_accounts`，键 → 账户 id）
2. 账户名 / 机构名里同时有尾号与银行名（或银行名的前两个字：「招商 0575」）
3. 零钱 / 支付宝余额：唯一一个名字带「微信」「零钱」/「支付宝」的电子钱包
都没有就建议新建一个账户（名字、类型、机构由原文推出），由用户在导入前确认。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.enums import AccountType
from app.db.models import Account
from app.services.preferences import get_pref, set_pref

HOME_WECHAT = "零钱"
HOME_ALIPAY = "支付宝余额"
# 平台自己的钱包（导入时排在映射列表最前）及认它的账户名关键词
HOMES: dict[str, tuple[str, ...]] = {
    HOME_WECHAT: ("微信", "零钱", "wechat"),
    HOME_ALIPAY: ("支付宝", "alipay"),
}
PREF_KEY = "payment_accounts"

_CARD = re.compile(r"^(?P<bank>.+?)(?P<kind>信用卡|储蓄卡|借记卡|银行卡)?\s*[(](?P<last4>\d{4})[)]$")


def _nfkc(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").split())


def method_key(label: str) -> str:
    """「招商银行信用卡(0575)」「招商银行(0575)」→「招商银行(0575)」；其余原样（NFKC、压空白）。"""
    s = _nfkc(label)
    m = _CARD.match(s)
    if m:
        return f"{m['bank'].strip()}({m['last4']})"
    return s


@dataclass(frozen=True)
class NewAccount:
    name: str
    type: AccountType
    institution: str | None


def new_account_for(label: str) -> NewAccount:
    s = _nfkc(label)
    if s == HOME_WECHAT:
        return NewAccount("微信零钱", AccountType.emoney, "微信支付")
    if s == HOME_ALIPAY:
        return NewAccount("支付宝余额", AccountType.emoney, "支付宝")
    if s in ("零钱通", "理财通"):
        return NewAccount(s, AccountType.investment, "微信支付")
    if s == "余额宝":
        return NewAccount(s, AccountType.investment, "支付宝")
    if "分付" in s:
        return NewAccount("微信分付", AccountType.credit_card, "微信支付")
    if "花呗" in s:
        return NewAccount("花呗", AccountType.credit_card, "支付宝")
    m = _CARD.match(s)
    if m:
        bank, kind = m["bank"].strip(), m["kind"] or ""
        type_ = AccountType.credit_card if kind == "信用卡" else AccountType.bank
        return NewAccount(f"{bank}{kind} {m['last4']}", type_, bank)
    return NewAccount(s, AccountType.emoney, None)


def _compact(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text or "").lower() if ch.isalnum())


def _guess(accounts: list[Account], key: str) -> int | None:
    m = _CARD.match(key)
    if m:
        bank, last4 = m["bank"].strip(), m["last4"]
        short = _compact(bank)[:2]  # 「招商银行」→「招商」
        for a in accounts:
            text = _compact(f"{a.name} {a.institution or ''}")
            if last4 in text and (_compact(bank) in text or (short and short in text)):
                return a.id
        return None
    if key in HOMES:
        wallets = [
            a for a in accounts
            if a.type == AccountType.emoney and any(w in _compact(a.name) for w in HOMES[key])
        ]
        return wallets[0].id if len(wallets) == 1 else None
    for a in accounts:
        if _compact(a.name) == _compact(key):
            return a.id
    return None


def resolve(db: Session, user_id: int, keys: list[str]) -> dict[str, int | None]:
    """每个键当前能对上的账户 id（对不上为 None）。"""
    accounts = db.query(Account).filter(Account.user_id == user_id, Account.is_archived.is_(False)).all()
    alive = {a.id for a in accounts}
    saved = get_pref(db, user_id, PREF_KEY) or {}
    out: dict[str, int | None] = {}
    for key in keys:
        remembered = saved.get(key) if isinstance(saved, dict) else None
        out[key] = remembered if remembered in alive else _guess(accounts, key)
    return out


def remember(db: Session, user_id: int, mapping: dict[str, int]) -> None:
    saved = get_pref(db, user_id, PREF_KEY)
    merged = dict(saved) if isinstance(saved, dict) else {}
    merged.update(mapping)
    set_pref(db, user_id, PREF_KEY, merged)
