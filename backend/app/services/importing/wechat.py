"""微信支付账单 → RawTransaction 列表（需求书附录 C）。

微信「账单 → 常见问题 → 下载账单」导出的明细：2024 年起是 xlsx，之前是 UTF-8 的 CSV，
两者列结构相同——前十几行是说明（昵称、起止时间、收支合计），之后一行列标题：

    交易时间, 交易类型, 交易对方, 商品, 收/支, 金额(元), 支付方式, 当前状态, 交易单号, 商户单号, 备注

与日本卡商明细的根本差异：**一份文件跨多个账户**。「支付方式」写的是钱实际从哪出：
零钱，或绑定的某张银行卡（「招商银行信用卡(0575)」）。每行据此带上 account_hint，
由管道按用户确认的映射落到对应账户——绑卡支付记在那张卡上，而不是记在零钱上。

各类交易的处理：

- 收/支 = 支出 / 收入：普通收支。收入行支付方式为「/」时钱进了零钱（当前状态「已存入零钱」）
- 收/支 = 「/」（中性交易：提现、充值、零钱通、理财通、信用卡还款）：转账，不计收支
  - 零钱提现：金额**含服务费**（备注「服务费¥9.00」，9009 = 到账 9000 + 9），
    拆成「零钱 → 银行卡 9000」的转账与一笔 9 元手续费支出
  - 零钱充值：银行卡 → 零钱
- 退款是独立的一行（交易类型「xxx-退款」，收入），原交易照记全额，状态里带「已退款(¥38.00)」。
  两行都入账，余额才对得上；退款行归入「退款」
- 微信红包 / 转账：给出人情往来类目提示（红包很确定，转账给人只是默认，商家记忆优先）
- 金额是元，两位小数 → 按分存（人民币地区包 minor_unit = 2）
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

from app.services.importing.payment_methods import HOME_WECHAT
from app.services.importing.xlsx import excel_serial_to_datetime
from app.services.ocr.base import RawTransaction
from app.services.parsing.amounts import parse_amount

MINOR_UNIT = 2  # 微信账单的金额单位是元，两位小数

HEADER = ("交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态")

_FAILED = re.compile(r"失败|已关闭|已撤销|已取消|未支付")
_FEE = re.compile(r"服务费\s*[¥￥]?\s*([\d,]+(?:\.\d+)?)")
_REFUNDED = re.compile(r"已退款\s*[(（]?\s*[¥￥]?\s*([\d,]+(?:\.\d+)?)")
_DATETIME = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
# 「商品」列里的线索 → 类目。交易对方常是没听过的店名或个人收款码，商品列反而说清了是什么
_GOODS_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"外卖"), "food.delivery"),
    (re.compile(r"点餐|堂食|餐饮|用餐"), "food.dining"),
    (re.compile(r"打车|快车|出租车"), "transport.taxi"),
    (re.compile(r"地铁|公交|乘车"), "transport.transit"),
    (re.compile(r"话费"), "comm.mobile"),
    (re.compile(r"火车票|机票|车票"), "transport.intercity"),
)

# 「商品」列里没有信息量的占位
_BORING_GOODS = {"/", "", "收款方备注:二维码收款", "转账备注:微信转账", "二维码收款"}


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def find_header(rows: list[list[str]]) -> int | None:
    """列标题行的位置；不是微信账单返回 None。说明区约 15 行，多看一些容错。"""
    for i, row in enumerate(rows[:60]):
        cells = [_nfkc(c) for c in row]
        if all(h in cells for h in HEADER):
            return i
    return None


def parse_when(text: str) -> dt.datetime | None:
    """xlsx 里是 Excel 序列号，CSV 里是「2026-09-03 11:32:28」。"""
    t = (text or "").strip()
    m = _DATETIME.search(t)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        try:
            return dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
        except ValueError:
            return None
    return excel_serial_to_datetime(t)


def clean_cell(s: str) -> str:
    """单元格里的值：去首尾空白（CSV 版每格后面常跟一个 Tab），「/」视为空。"""
    v = (s or "").strip()
    return "" if v == "/" else v


# 订单号、商户单号这类长编号（可带字母前缀）：备注里留着只是噪音
_ORDER_ID = re.compile(r"[\s\-_:：]*(?:订单号?|商户单号|单号)?[\s:：\-]*[A-Za-z]*\d{12,}[\s\-_]*")


def _memo(goods: str, partner: str) -> str | None:
    """「商品」列 → 备注。美团订单里写着真正的店名（「郑世隆古法泰茶（…店）-美团App-2602…」），
    值得留；单号、和交易对方重复的公司名、「二维码收款」之类的占位去掉。"""
    g = " ".join(clean_cell(goods).split())
    if g in _BORING_GOODS or g == partner:
        return None
    for prefix in ("转账备注:", "收款方备注:", "付款方留言:"):
        if g.startswith(prefix):
            g = g[len(prefix):].strip()
    g = _ORDER_ID.sub(" ", g).strip(" -_:：")
    if not g or g in ("订单", "订单号", "商户单号") or g == partner:
        return None
    return g


def parse_rows(rows: list[list[str]], header_at: int) -> list[RawTransaction]:
    header = [_nfkc(c) for c in rows[header_at]]
    col = {name: i for i, name in enumerate(header)}

    out: list[RawTransaction] = []
    for row in rows[header_at + 1:]:
        def get(name: str) -> str:
            i = col.get(name)
            return row[i] if i is not None and i < len(row) else ""

        raw_text = ",".join(c.strip() for c in row)
        when = parse_when(get("交易时间"))
        kind = _nfkc(get("交易类型"))
        partner = " ".join(clean_cell(get("交易对方")).split())
        side = clean_cell(get("收/支"))
        method = clean_cell(get("支付方式"))
        status = _nfkc(get("当前状态"))
        remark = _nfkc(get("备注"))
        amount = parse_amount(get("金额(元)"), MINOR_UNIT)

        if when is None:
            # 末尾偶尔有说明行；不是交易就跳过，不当成「无日期」打扰用户
            if not kind and amount is None:
                continue
            out.append(RawTransaction(merchant_raw=partner or kind, excluded=True, exclude_reason="no_date", raw_text=raw_text))
            continue
        if amount is None:
            out.append(
                RawTransaction(date=when.date(), merchant_raw=partner or kind, excluded=True,
                               exclude_reason="no_amount", raw_text=raw_text)
            )
            continue

        base = dict(date=when.date(), time=when.time(), confidence=0.98, raw_text=raw_text)
        memo = _memo(get("商品"), partner)
        refunded = _REFUNDED.search(status)
        if refunded and side == "支出":
            note = f"已退款 ¥{refunded.group(1)}"
            memo = f"{memo} · {note}" if memo else note

        if _FAILED.search(status):
            out.append(RawTransaction(amount=amount, merchant_raw=partner or kind, direction="expense",
                                      excluded=True, exclude_reason="failed", **base))
            continue

        # ---- 中性交易：转账 ----
        if side not in ("支出", "收入"):
            out.extend(_neutral(kind, partner, method, amount, remark, base))
            continue

        direction = "expense" if side == "支出" else "income"
        account = method or HOME_WECHAT
        goods = _nfkc(get("商品"))
        fallback = next((key for pat, key in _GOODS_HINTS if pat.search(goods)), None) if direction == "expense" else None
        merchant = partner or kind
        hint: str | None = None

        if kind.startswith("微信红包"):
            if direction == "expense":
                # 「发给AKi」「发出群红包」
                merchant = re.sub(r"^发给", "", merchant)
                merchant = "群红包" if merchant == "发出群红包" else merchant
                hint = "social.redpacket"
            else:
                hint = "income.redpacket"
            memo = memo or "微信红包"
        elif kind == "转账":
            hint = "social.transfer" if direction == "expense" else "income.transfer"
        elif direction == "income" and ("退款" in kind or status.startswith("已退款") or "退还" in status):
            hint = "income.refund"

        out.append(
            RawTransaction(
                amount=abs(amount),
                merchant_raw=merchant,
                direction=direction,
                account_hint=account,
                category_hint=hint,
                category_fallback=fallback,
                memo=memo,
                transfer=False,
                **base,
            )
        )
    return out


def _neutral(kind: str, partner: str, method: str, amount: int, remark: str, base: dict) -> list[RawTransaction]:
    """中性交易 → 转账（+ 提现服务费）。认不出方向的照样标转账，对方账户交给用户选。"""
    # 提示里放支付方式原文，由管道归一成键（payment_methods.method_key）再查映射
    method_k = method or HOME_WECHAT
    src, dst, direction = method_k, None, "expense"
    out: list[RawTransaction] = []

    if kind.startswith("零钱提现"):
        src, dst = HOME_WECHAT, method or partner or None
        fee_m = _FEE.search(remark)
        fee = parse_amount(fee_m.group(1), MINOR_UNIT) if fee_m else None
        if fee and 0 < fee < amount:
            amount -= fee
            out.append(
                RawTransaction(
                    amount=fee,
                    merchant_raw="提现服务费",
                    direction="expense",
                    account_hint=HOME_WECHAT,
                    category_hint="finance.fee",
                    transfer=False,
                    memo=partner or None,
                    **base,
                )
            )
    elif kind.startswith("零钱充值"):
        # 钱进零钱：以零钱为本账户、方向收入，对方是扣款的银行卡
        src, dst, direction = HOME_WECHAT, method_k if method else None, "income"
    elif "零钱通" in kind:
        if kind.startswith("转入零钱通") or kind.startswith("零钱通转入"):
            src, dst = method_k, "零钱通"
        else:
            src, dst = "零钱通", method_k
    elif "理财通" in kind:
        if "赎回" in kind or "转出" in kind:
            src, dst = "理财通", method_k
        else:
            src, dst = method_k, "理财通"
    elif "还款" in kind:
        # 信用卡还款：对方是被还的那张卡，常写在交易对方里（「招商银行(0575)」）
        dst = partner if partner and re.search(r"\(\d{4}\)", _nfkc(partner)) else None

    merchant = f"{kind} {partner}".strip() if partner and partner not in kind else kind
    out.insert(
        0,
        RawTransaction(
            amount=amount,
            merchant_raw=merchant,
            direction=direction,
            account_hint=src,
            counterpart_hint=dst,
            transfer=True,
            **base,
        ),
    )
    return out
