from __future__ import annotations

import re

from app.db.enums import AccountType
from app.db.models import Account
from app.services.normalize import normalize_merchant

_ALIASES: tuple[tuple[str, str], ...] = (
    ("ペイペイ", "paypay"),
    ("ラクテン", "楽天"),
    ("ミツイスミトモ", "三井住友"),
    ("ユウチヨ", "ゆうちょ"),
    ("ミズホ", "みずほ"),
    ("リソナ", "りそな"),
    ("セブンギンコウ", "セブン銀行"),
    ("ジエイウエスト", "j-west"),
    ("jwest", "j-west"),
    ("ラインペイ", "linepay"),
    ("メルペイ", "メルペイ"),
    ("シヨウケン", "証券"),
    ("ギンコウ", "銀行"),
)

_ATM = re.compile(r"atm|引き出し|カード出金|^カード")
_CHARGE = re.compile(r"チャージ|オートチャージ")
_SECURITIES = re.compile(r"証券|シヨウケン")
_CARD_PAYMENT = re.compile(r"カードサービス|カード引落|カード代金|カード")


def _keys(account: Account) -> set[str]:
    out = set()
    for raw in (account.name, account.institution or ""):
        k = normalize_merchant(raw)
        if len(k) >= 2:
            out.add(k)
    return out


def suggest_counterpart(
    accounts: list[Account],
    account: Account,
    merchant_raw: str,
    direction: str,
) -> int | None:
    others = [a for a in accounts if a.id != account.id and not a.is_archived]
    if not others:
        return None

    norm = normalize_merchant(merchant_raw)
    aliased = norm
    for src, dst in _ALIASES:
        aliased = aliased.replace(src, dst)

    for a in others:
        for key in _keys(a):
            if key in norm or key in aliased:
                return a.id

    def only(kind: AccountType) -> int | None:
        found = [a for a in others if a.type == kind]
        return found[0].id if len(found) == 1 else None

    if _ATM.search(norm):
        return only(AccountType.cash)
    if _CHARGE.search(norm):
        if account.type in (AccountType.emoney, AccountType.prepaid):
            return only(AccountType.bank)
        return only(AccountType.emoney) or only(AccountType.prepaid)
    if _SECURITIES.search(norm):
        return only(AccountType.investment)
    if _CARD_PAYMENT.search(norm) and account.type == AccountType.bank and direction == "expense":
        return only(AccountType.credit_card)
    return None
