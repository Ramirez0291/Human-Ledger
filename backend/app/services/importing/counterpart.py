"""转账对方账户的自动推荐（需求书 A.5.2 的延伸）。

词典只能判断「这行像转账」，对方是谁要看用户有哪些账户：

- 商家名里带对方账户的名字 / 机构名：`チャージ 三井住友銀行 *****12`、`ﾗｸﾃﾝｶ-ﾄﾞｻ-ﾋﾞｽ`
- 按账户类型兜底：ATM 取现 ↔ 现金；电子钱包的充值 ↔ 银行；卡还款 ↔ 信用卡。
  只有当同类账户唯一时才敢猜，两个银行账户就交给用户

推荐结果直接预填到待确认行的 counterpart_account_id，用户可改可清。
电子钱包（PayPay 等）的钱几乎都来自银行自动充值，这一步省掉的是每月十几次手选。
"""

from __future__ import annotations

import re

from app.db.enums import AccountType
from app.db.models import Account
from app.services.normalize import normalize_merchant

# 银行 / 卡明细里对方名字的片假名写法 → 账户名里常见的写法。
# 规范化后的商家名先做这层替换，再与账户名比对。
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
    """一个账户可被识别的名字：账户名、机构名，各自规范化。太短的（≤1 字）不要。"""
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

    # 1. 名字直接出现在商家名里
    for a in others:
        for key in _keys(a):
            if key in norm or key in aliased:
                return a.id

    # 2. 按类型兜底，仅在同类账户唯一时
    def only(kind: AccountType) -> int | None:
        found = [a for a in others if a.type == kind]
        return found[0].id if len(found) == 1 else None

    if _ATM.search(norm):
        return only(AccountType.cash)
    if _CHARGE.search(norm):
        # 电子钱包 / IC 卡上的充值：钱来自银行；银行上的充值：钱去了钱包
        if account.type in (AccountType.emoney, AccountType.prepaid):
            return only(AccountType.bank)
        return only(AccountType.emoney) or only(AccountType.prepaid)
    if _SECURITIES.search(norm):
        return only(AccountType.investment)
    if _CARD_PAYMENT.search(norm) and account.type == AccountType.bank and direction == "expense":
        return only(AccountType.credit_card)
    return None
