"""支付宝交易明细 → RawTransaction 列表（需求书附录 D）。

支付宝 App「我的 → 账单 → … → 开具交易流水证明 → 用于个人对账」导出的 CSV：GBK 编码，
前二十来行是说明（姓名、账号、起止时间、收支合计、特别提示），之后一行列标题：

    交易时间, 交易分类, 交易对方, 对方账号, 商品说明, 收/支, 金额, 收/付款方式, 交易状态, 交易订单号, 商家订单号, 备注

与微信账单一样**一份文件跨多个账户**：「收/付款方式」是钱实际从哪出——账户余额、余额宝、花呗、
绑定的银行卡（「中国银行储蓄卡(6721)&优惠」）。卡键与微信共用（payment_methods.method_key），
同一张卡在两份账单里落到同一个账户。

各类交易的处理：

- 交易状态「交易关闭」：订单取消（没付款，或付了又全额退回），钱没有净流动 → 排除（closed）
- 金额 0.00：先用后付下单时的占位行，真正扣款是之后另一行 → 排除（zero_amount）
- 收/付款方式写成「卡&优惠」「卡&中国银行立减金」：金额已是实付，优惠 / 立减金 / 红包这类不是账户，去掉
- 退款（交易分类「退款」/ 状态「退款成功」/ 商品说明「退款-…」）：收入，归入「退款」。
  原订单在同一份文件里是「交易关闭」时，这笔退款连同原订单一起排除（refund_of_closed），否则会凭空多一笔收入
- 收/支 =「不计收支」且不是关闭 / 退款：余额宝转入转出、充值、提现、花呗 / 信用卡还款 → 转账
- 「交易分类」是支付宝按商户给的分类，转成类目提示：比我们按店名猜的词典可靠
  （淘宝店名多是「tb127782865」），但让位于用户规则与商家记忆；词典给出的是同一大类下的子类时用词典的
"""

from __future__ import annotations

import re
import unicodedata

from app.services.importing.payment_methods import HOME_ALIPAY
from app.services.importing.wechat import clean_cell, parse_when
from app.services.ocr.base import RawTransaction
from app.services.parsing.amounts import parse_amount

MINOR_UNIT = 2

HEADER = ("交易时间", "交易分类", "交易对方", "商品说明", "收/支", "金额", "收/付款方式", "交易状态")

# 支付宝交易分类 → 中国地区包的类目键。粗的给大类（「餐饮美食」可能是餐厅也可能是网购零食），
# 细的给子类；说明不了什么的（其他 / 商业服务 / 生活服务 / 充值缴费）不给
CATEGORY_MAP: dict[str, str] = {
    "餐饮美食": "food",
    "服饰装扮": "shopping.clothing",
    "日用百货": "shopping.daily",
    "数码电器": "shopping.digital",
    "家居家装": "housing.repair",
    "爱车养车": "transport.car",
    "交通出行": "transport",
    "文化休闲": "entertainment",
    "运动户外": "entertainment.hobby",
    "酒店旅游": "entertainment.travel",
    "教育培训": "education",
    "医疗健康": "medical",
    "美容美发": "beauty",
    "母婴亲子": "family.kids",
    "宠物": "family.pets",
    "保险": "insurance",
    "公益": "social",
}

_CLOSED = re.compile(r"交易关闭|已关闭")
_FAILED = re.compile(r"失败|已撤销|已取消")
_REFUND = re.compile(r"退款")
# 「&」后面不是账户的部分：优惠券、立减金、红包、积分抵扣
_NOT_ACCOUNT = re.compile(r"优惠|立减|红包|集分宝|积分|折扣|券|抵扣")
_CARD = re.compile(r"\(\d{4}\)")


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def find_header(rows: list[list[str]]) -> int | None:
    for i, row in enumerate(rows[:60]):
        cells = [_nfkc(c) for c in row]
        if all(h in cells for h in HEADER):
            return i
    return None


def _method(raw: str) -> str:
    """「中国银行储蓄卡(6721)&优惠」→「中国银行储蓄卡(6721)」；「余额」「账户余额」→「支付宝余额」；空 → ""。"""
    parts = [p.strip() for p in clean_cell(raw).split("&")]
    parts = [p for p in parts if p and not _NOT_ACCOUNT.search(p)]
    if not parts:
        return ""
    first = parts[0]
    return HOME_ALIPAY if first in ("余额", "账户余额", "支付宝余额") else first


def _memo(goods: str, partner: str) -> str | None:
    """商品说明 → 备注。淘宝的交易对方多是「tb127782865」「x***3」，买了什么全在这一列里。"""
    g = " ".join(clean_cell(goods).split())
    if not g or g == partner:
        return None
    return g if len(g) <= 80 else g[:79] + "…"


def parse_rows(rows: list[list[str]], header_at: int) -> list[RawTransaction]:
    header = [_nfkc(c) for c in rows[header_at]]
    col = {name: i for i, name in enumerate(header) if name}

    parsed: list[tuple[dict, RawTransaction]] = []
    for row in rows[header_at + 1:]:
        def get(name: str) -> str:
            i = col.get(name)
            return row[i] if i is not None and i < len(row) else ""

        raw_text = ",".join(c.strip() for c in row)
        when = parse_when(get("交易时间"))
        kind = _nfkc(get("交易分类"))
        partner = " ".join(clean_cell(get("交易对方")).split())
        goods = clean_cell(get("商品说明"))
        side = clean_cell(get("收/支"))
        status = _nfkc(get("交易状态"))
        method = _method(get("收/付款方式"))
        amount = parse_amount(get("金额"), MINOR_UNIT)
        ids = {"trade": clean_cell(get("交易订单号")), "order": clean_cell(get("商家订单号")), "status": status}

        if when is None:
            if not kind and amount is None:
                continue  # 末尾的空行 / 说明
            parsed.append((ids, RawTransaction(merchant_raw=partner or kind, excluded=True,
                                               exclude_reason="no_date", raw_text=raw_text)))
            continue

        base = dict(date=when.date(), time=when.time(), confidence=0.98, raw_text=raw_text)
        merchant = partner or goods or kind
        memo = _memo(goods, partner)
        direction = "income" if side == "收入" else "expense"

        def excluded(reason: str) -> RawTransaction:
            return RawTransaction(amount=amount, merchant_raw=merchant, direction=direction, memo=memo,
                                  excluded=True, exclude_reason=reason, **base)

        if amount is None:
            parsed.append((ids, excluded("no_amount")))
        elif _FAILED.search(status):
            parsed.append((ids, excluded("failed")))
        elif _CLOSED.search(status):
            parsed.append((ids, excluded("closed")))
        elif amount == 0:
            parsed.append((ids, excluded("zero_amount")))
        elif kind == "退款" or _REFUND.search(status) or goods.startswith("退款"):
            ids["refund"] = True
            parsed.append((ids, RawTransaction(
                amount=amount, merchant_raw=merchant, direction="income",
                account_hint=method or HOME_ALIPAY, category_hint="income.refund",
                memo=memo, transfer=False, **base,
            )))
        elif side in ("支出", "收入"):
            parsed.append((ids, RawTransaction(
                amount=amount, merchant_raw=merchant, direction=direction,
                account_hint=method or HOME_ALIPAY,
                category_hint=_hint(kind, goods, direction),
                memo=memo, transfer=False, **base,
            )))
        else:
            parsed.append((ids, _neutral(kind, partner, goods, method, amount, memo, base)))

    _drop_refunds_of_closed(parsed)
    return [t for _, t in parsed]


def _hint(kind: str, goods: str, direction: str) -> str | None:
    if kind == "转账红包":
        red = "红包" in goods
        if direction == "expense":
            return "social.redpacket" if red else "social.transfer"
        return "income.redpacket" if red else "income.transfer"
    if direction == "expense":
        return CATEGORY_MAP.get(kind)
    return None


def _neutral(kind: str, partner: str, goods: str, method: str, amount: int, memo: str | None, base: dict) -> RawTransaction:
    """不计收支（且没关闭、不是退款）→ 转账。认得出方向的给出对方账户，认不出的交给用户。"""
    text = f"{kind} {partner} {goods}"
    src, dst, direction = method or HOME_ALIPAY, None, "expense"
    if "余额宝" in text:
        if re.search(r"转出|赎回", text):
            src, dst = "余额宝", method if method and method != "余额宝" else HOME_ALIPAY
        elif src != "余额宝":
            dst = "余额宝"
    elif "提现" in text:
        src = HOME_ALIPAY
        dst = method if method and method != HOME_ALIPAY else next((p for p in (partner, goods) if _CARD.search(_nfkc(p))), None)
    elif "充值" in text:
        # 钱进余额：以余额为本账户、方向收入，对方是扣款的卡
        src, dst, direction = HOME_ALIPAY, method if method and method != HOME_ALIPAY else None, "income"
    elif "还款" in text:
        dst = "花呗" if "花呗" in text else next((p for p in (partner, goods) if _CARD.search(_nfkc(p))), None)
    merchant = " ".join(x for x in (kind if kind not in ("其他", "") else "", partner or goods) if x) or "支付宝"
    return RawTransaction(
        amount=amount, merchant_raw=merchant, direction=direction,
        account_hint=src, counterpart_hint=dst, transfer=True, memo=memo, **base,
    )


def _drop_refunds_of_closed(parsed: list[tuple[dict, RawTransaction]]) -> None:
    """原订单在文件里是「交易关闭」时，它的退款也不算：钱出去又回来，净额为零，原订单已经排除了。"""
    closed_trade = {ids["trade"] for ids, t in parsed if t.exclude_reason == "closed" and ids["trade"]}
    closed_order = {ids["order"] for ids, t in parsed if t.exclude_reason == "closed" and ids["order"]}
    for ids, t in parsed:
        if not ids.get("refund") or t.excluded:
            continue
        trade = ids["trade"]
        if (ids["order"] and ids["order"] in closed_order) or any(trade.startswith(c) for c in closed_trade if trade):
            t.excluded, t.exclude_reason = True, "refund_of_closed"
