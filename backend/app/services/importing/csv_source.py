"""CSV 来源：银行 / 信用卡官网下载的明细 → RawTransaction 列表（需求书 F9）。

两层机制：

1. **已知格式（Profile）**：按首行特征自动识别，无需用户配置。
   - smbc_card     三井住友カード / Olive クレジット 的月度明细
   - smbc_bank     三井住友銀行 口座明細
   - rakuten_card  楽天カード e-NAVI 月度明细（enaviYYYYMM(xxxx).csv）
   - paypay        PayPay 取引履歴（Transactions_YYYYMMDD-YYYYMMDD.csv）
2. **通用映射**：未识别的格式，由用户指定各列的角色（日期 / 商家 / 金额 …）。
   映射方案可保存复用（按列标题签名自动匹配）。

编码：日本金融机构的 CSV 绝大多数是 Shift_JIS（cp932）。依次尝试
utf-8-sig → utf-8 → cp932 → euc_jp，UTF-8 严格解码在 Shift_JIS 字节上会很快失败，
因此顺序安全。
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import re
import unicodedata
from dataclasses import dataclass, field

from app.services.ocr.base import ExtractResult, RawTransaction
from app.services.parsing.amounts import parse_amount
from app.services.parsing.dates import parse_date

ENCODINGS = ("utf-8-sig", "utf-8", "cp932", "euc_jp")


def decode(content: bytes) -> tuple[str, str]:
    """返回 (文本, 编码名)。全部失败时以 cp932 宽松解码，不让一个坏字节挡住整个文件。"""
    for enc in ENCODINGS:
        try:
            return content.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return content.decode("cp932", errors="replace"), "cp932?"


def read_rows(text: str) -> list[list[str]]:
    """解析为二维表。自动识别逗号 / Tab 分隔；去掉每个单元格首尾空白。"""
    sample = text[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        cells = [c.strip() for c in row]
        if any(cells):
            rows.append(cells)
    return rows


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


# --------------------------------------------------------------------------
# 映射（通用格式）
# --------------------------------------------------------------------------


@dataclass
class ColumnMapping:
    """各列角色。索引从 0 起；None 表示该角色不存在。

    金额有两种表达：单列带符号（amount），或出金 / 入金分列（withdrawal / deposit）。
    """

    date: int
    merchant: int
    amount: int | None = None
    withdrawal: int | None = None
    deposit: int | None = None
    balance: int | None = None
    memo: int | None = None
    # 单列金额时：正数是支出还是收入。信用卡明细正数是支出；有些银行导出正数是入金
    positive_is_expense: bool = True
    has_header: bool = True
    skip_rows: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnMapping":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# 列标题关键词 → 角色，用于向用户建议映射
_HEADER_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("date", re.compile(r"日付|年月日|取引日|利用日|ご利用日|date", re.I)),
    ("withdrawal", re.compile(r"出金|引出|お引出し|払戻|withdraw|debit", re.I)),
    ("deposit", re.compile(r"入金|預入|お預入れ|預り|deposit|credit", re.I)),
    ("amount", re.compile(r"金額|利用金額|ご利用金額|amount", re.I)),
    ("balance", re.compile(r"残高|balance", re.I)),
    ("merchant", re.compile(r"内容|摘要|店名|利用店|ご利用店|取引内容|お取り扱い内容|description|merchant", re.I)),
    ("memo", re.compile(r"メモ|備考|memo|note", re.I)),
]


def suggest_mapping(header: list[str]) -> ColumnMapping | None:
    """按列标题猜测映射。猜不出日期与商家列时返回 None。"""
    found: dict[str, int] = {}
    for idx, col in enumerate(header):
        name = _nfkc(col)
        for role, pat in _HEADER_HINTS:
            if role in found:
                continue
            if pat.search(name):
                found[role] = idx
                break
    if "date" not in found or "merchant" not in found:
        return None
    return ColumnMapping(
        date=found["date"],
        merchant=found["merchant"],
        amount=found.get("amount"),
        withdrawal=found.get("withdrawal"),
        deposit=found.get("deposit"),
        balance=found.get("balance"),
        memo=found.get("memo"),
        has_header=True,
    )


def header_signature(header: list[str]) -> str:
    """列标题签名，用于匹配已保存的映射方案。"""
    return "|".join(_nfkc(h).strip().lower() for h in header)


# --------------------------------------------------------------------------
# 已知格式
# --------------------------------------------------------------------------


@dataclass
class Profile:
    key: str
    name: str
    institution: str
    account_kind: str  # "credit_card" | "bank"


@dataclass
class Detected:
    profile: Profile | None
    mapping: ColumnMapping | None
    header: list[str]
    data_start: int
    # 从文件名 / 首行推断出的支払月（信用卡）
    statement_month: dt.date | None = None
    notes: list[str] = field(default_factory=list)


SMBC_CARD = Profile("smbc_card", "三井住友カード / Olive クレジット", "三井住友カード", "credit_card")
SMBC_BANK = Profile("smbc_bank", "三井住友銀行 口座明細", "三井住友銀行", "bank")
RAKUTEN_CARD = Profile("rakuten_card", "楽天カード e-NAVI", "楽天カード", "credit_card")
PAYPAY = Profile("paypay", "PayPay 取引履歴", "PayPay", "emoney")

PROFILES: dict[str, Profile] = {p.key: p for p in (SMBC_CARD, SMBC_BANK, RAKUTEN_CARD, PAYPAY)}

_SMBC_BANK_HEADER = ("年月日", "お引出し", "お預入れ", "お取り扱い内容", "残高")
# 楽天カード：第 8 / 10 列标题含月份（「6月支払金額」），只比对前 7 列固定的部分
_RAKUTEN_HEADER = ("利用日", "利用店名・商品名", "利用者", "支払方法", "利用金額", "手数料/利息", "支払総額")
_PAYPAY_REQUIRED = ("取引日", "出金金額(円)", "入金金額(円)", "取引内容", "取引先", "取引方法")
_CARD_MASK = re.compile(r"\d{4}-\d{2}\*{2}-\*{4}-\*{4}")


def detect(rows: list[list[str]], filename: str = "") -> Detected:
    if not rows:
        return Detected(None, None, [], 0)

    first = [_nfkc(c) for c in rows[0]]

    # ---- 三井住友銀行 口座明細：固定表头 ----
    if len(first) >= 5 and tuple(first[:5]) == _SMBC_BANK_HEADER:
        return Detected(
            SMBC_BANK,
            ColumnMapping(date=0, withdrawal=1, deposit=2, merchant=3, balance=4, memo=5 if len(first) > 5 else None),
            rows[0],
            1,
        )

    # ---- 三井住友カード：首行是「持卡人, 掩码卡号, 卡种」，无列标题 ----
    if len(first) >= 3 and _CARD_MASK.search(first[1]):
        statement = None
        m = re.search(r"(20\d{2})(0[1-9]|1[0-2])", filename or "")
        if m:
            statement = dt.date(int(m.group(1)), int(m.group(2)), 1)
        return Detected(
            SMBC_CARD,
            ColumnMapping(date=0, merchant=1, amount=2, memo=6, has_header=False),
            [],
            1,
            statement_month=statement,
            notes=[f"card:{first[2]}"],
        )

    # ---- 楽天カード e-NAVI ----
    if len(first) >= 9 and tuple(first[:7]) == _RAKUTEN_HEADER:
        statement = None
        m = re.search(r"enavi(20\d{2})(0[1-9]|1[0-2])", filename or "")
        if m:
            statement = dt.date(int(m.group(1)), int(m.group(2)), 1)
        return Detected(
            RAKUTEN_CARD,
            ColumnMapping(date=0, merchant=1, amount=8, memo=3),
            rows[0],
            1,
            statement_month=statement,
        )

    # ---- PayPay 取引履歴：按列名定位，列顺序变了也不怕 ----
    if all(col in first for col in _PAYPAY_REQUIRED):
        idx = {name: first.index(name) for name in first}
        return Detected(
            PAYPAY,
            ColumnMapping(
                date=idx["取引日"],
                merchant=idx["取引先"],
                withdrawal=idx["出金金額(円)"],
                deposit=idx["入金金額(円)"],
                memo=idx["取引方法"],
            ),
            rows[0],
            1,
        )

    # ---- 通用：按表头猜 ----
    mapping = suggest_mapping(rows[0])
    if mapping is not None:
        return Detected(None, mapping, rows[0], 1)
    return Detected(None, None, rows[0], 0)


# --------------------------------------------------------------------------
# 行 → RawTransaction
# --------------------------------------------------------------------------


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _smbc_card_row(row: list[str], anchor: dt.date | None) -> RawTransaction | None:
    """三井住友カード 明细行。

    列：日付, 利用店名, 利用金額, 支払区分, 回数, 今回請求額, 備考
    - 合计行：日期与店名为空，只有今回請求額 → 排除（汇总行）
    - 分期：回数 > 1 时，利用金額是总额，今回請求額才是当期金额（附录 A.5.1 口径）
    - 负数 + 備考「返品」→ 退款，计为收入
    - 海外交易：備考形如「13827.00 JPY 1.0000 08 04」
    """
    date_s, merchant, amount_s, _kind, times_s, this_month_s, memo = (
        _cell(row, i) for i in range(7)
    )
    if not date_s and not merchant:
        total = parse_amount(this_month_s)
        return RawTransaction(
            amount=total, merchant_raw="合計", excluded=True, exclude_reason="summary_row",
            raw_text=",".join(row),
        )

    parsed = parse_date(date_s, anchor=anchor)
    if parsed is None:
        return RawTransaction(
            merchant_raw=merchant, excluded=True, exclude_reason="no_date", raw_text=",".join(row)
        )

    total = parse_amount(amount_s)
    this_month = parse_amount(this_month_s)
    times = parse_amount(_nfkc(times_s)) or 1

    amount = this_month if this_month is not None else total
    if amount is None:
        return RawTransaction(
            date=parsed.date, merchant_raw=merchant, excluded=True, exclude_reason="no_amount",
            raw_text=",".join(row),
        )

    direction = "expense"
    if amount < 0:
        amount, direction = -amount, "income"

    installment = None
    date = parsed.date
    if times and times > 1 and total is not None:
        installment = {"total_times": times, "total_amount": abs(total)}
        date = _installment_date(parsed.date, anchor)

    return RawTransaction(
        date=date,
        amount=amount,
        merchant_raw=merchant,
        direction=direction,
        confidence=0.95,
        date_inferred=parsed.year_inferred,
        installment=installment,
        raw_text=",".join(row) + (f" | {memo}" if memo else ""),
    )


def _rakuten_amount_columns(header: list[str]) -> tuple[int | None, int | None]:
    """（N月支払金額 列号, 当月請求額 列号）。表头认不出时退回旧版固定列 7。"""
    names = [_nfkc(h) for h in header]
    pay = next((i for i, h in enumerate(names) if re.fullmatch(r"\d{1,2}月支払金額", h)), None)
    bill = next((i for i, h in enumerate(names) if h == "当月請求額"), None)
    if pay is None and bill is None:
        pay = 7
    return pay, bill


def _installment_date(purchase: dt.date, statement: dt.date | None) -> dt.date:
    """分期的每一期记在支払月，日取购买日（月底截断）。

    「按当期金额记」：每期是那个月真实发生的支出。卡商明细里每期都带着最初的利用日，
    原样入账的话 48 期全压在购买那天——那个月凭空多出几十万，之后的月份又看不到这笔开销；
    而且每期金额相同时指纹也相同，第二期起会被判成重复。不知道支払月时只好保留原日期。
    """
    if statement is None or (statement.year, statement.month) <= (purchase.year, purchase.month):
        return purchase
    last = calendar.monthrange(statement.year, statement.month)[1]
    return dt.date(statement.year, statement.month, min(purchase.day, last))


_INSTALLMENT = re.compile(r"分割\s*(\d+)\s*回払い\s*\(\s*(\d+)\s*回目\s*\)")
_RAKUTEN_TOTAL = re.compile(r"ご利用金額\s*[:：]\s*[\\¥]?\s*([\d,]+)")


def _rakuten_card_rows(
    rows: list[list[str]], header: list[str], anchor: dt.date | None
) -> list[RawTransaction]:
    """楽天カード e-NAVI 明细。

    列：利用日, 利用店名・商品名, 利用者, 支払方法, 利用金額, 手数料/利息, 支払総額,
        N月支払金額, [当月請求額,] M月繰越残高, 新規サイン
    - 2026/06 以前的文件没有「当月請求額」一列（10 列），之后有（11 列），
      所以当期金额按表头「N月支払金額」找列，不写死列号——写死第 9 列会在旧文件上
      读到繰越残高（普通消费是 0，分期是剩余本金）
    - 日期为空的行是上一笔的补充信息：ETC 的区间（「ｵｵｿﾞｳ ｵｵｿﾞｳ」）并入商家名，
      让往返两程有不同指纹（附录 A.4.1）；「ご利用金額：\\41487」是分期总额
    - 分期：支払方法「分割48回払い(14回目)」，当期金额取 N月支払金額；
      日期挪到支払月（见 _installment_date），否则 48 期全堆在购买那天
    - 退款：利用金額为负 → 收入
    """
    pay_col, bill_col = _rakuten_amount_columns(header)
    out: list[RawTransaction] = []
    last: RawTransaction | None = None
    for row in rows:
        date_s = _cell(row, 0)
        merchant = _cell(row, 1)
        if not date_s:
            if last is None or not merchant:
                continue
            m = _RAKUTEN_TOTAL.search(_nfkc(merchant))
            if m:
                total = parse_amount(m.group(1))
                if total is not None and last.installment is not None:
                    last.installment["total_amount"] = abs(total)
            else:
                # 多个连续空格压成一个；区间原文本身就是半角片假名
                last.merchant_raw = f"{last.merchant_raw} {' '.join(merchant.split())}"
            last.raw_text += " | " + ",".join(row)
            continue

        parsed = parse_date(date_s, anchor=anchor)
        if parsed is None:
            out.append(
                RawTransaction(
                    merchant_raw=merchant, excluded=True, exclude_reason="no_date",
                    raw_text=",".join(row),
                )
            )
            last = None
            continue

        method = _nfkc(_cell(row, 3))
        total = parse_amount(_cell(row, 4))
        grand_total = parse_amount(_cell(row, 6))
        this_month = parse_amount(_cell(row, pay_col)) if pay_col is not None else None
        if this_month is None and bill_col is not None:
            this_month = parse_amount(_cell(row, bill_col))
        amount = this_month if this_month is not None else total
        if amount is None:
            out.append(
                RawTransaction(
                    date=parsed.date, merchant_raw=merchant, excluded=True,
                    exclude_reason="no_amount", raw_text=",".join(row),
                )
            )
            last = None
            continue

        direction = "expense"
        if amount < 0:
            amount, direction = -amount, "income"

        installment = None
        date = parsed.date
        im = _INSTALLMENT.search(method)
        if im:
            installment = {
                "total_times": int(im.group(1)),
                "current_time": int(im.group(2)),
                "total_amount": abs(grand_total) if grand_total else abs(total or 0),
            }
            date = _installment_date(parsed.date, anchor)

        last = RawTransaction(
            date=date,
            amount=amount,
            merchant_raw=merchant,
            direction=direction,
            confidence=0.95,
            date_inferred=parsed.year_inferred,
            installment=installment,
            raw_text=",".join(row),
        )
        out.append(last)
    return out


# PayPay 取引内容 → 商家名前缀。没列出的种类按普通收支处理，商家名取取引先。
_PAYPAY_KIND_PREFIX = {
    "ポイント、残高の獲得": "ポイント獲得",
    "期間限定ポイントの期限切れ": "ポイント期限切れ",
    "送った金額": "送金",
    "受け取った金額": "受取",
}
_PAYPAY_BY_CARD = re.compile(r"クレジット|あと払い|カード")


def _paypay_row(row: list[str], header: list[str]) -> RawTransaction | None:
    """PayPay 取引履歴。

    - 取引日含时间「2026/09/17 19:54:36」
    - 出金 / 入金 分列，未用的一侧为「-」
    - チャージ：从银行充值，取引先是「PayPay」、取引方法是银行名 → 商家名写成
      「チャージ 三井住友銀行 *****12」，词典据此给出转账提示
    - 用 PayPay 但实际走信用卡（取引方法含「クレジット」「あと払い」）的支付不动余额，
      会出现在卡账单里，此处排除以免双计
    - 取引方法（残高 / ポイント 组合）留在 raw_text 供核对
    """
    col = {name: i for i, name in enumerate(_nfkc(h) for h in header)}

    def get(name: str) -> str:
        i = col.get(name)
        v = _cell(row, i) if i is not None else ""
        return "" if v in ("-", "－") else v

    date_s = get("取引日")
    kind = _nfkc(get("取引内容"))
    partner = get("取引先")
    method = get("取引方法")
    w = parse_amount(get("出金金額(円)"))
    d = parse_amount(get("入金金額(円)"))

    parsed = parse_date(date_s.split(" ")[0]) if date_s else None
    time = None
    tm = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", date_s)
    if tm:
        time = dt.time(int(tm.group(1)), int(tm.group(2)), int(tm.group(3) or 0))

    if parsed is None:
        return RawTransaction(
            merchant_raw=partner or kind, excluded=True, exclude_reason="no_date",
            raw_text=",".join(row),
        )

    amount: int | None
    if w:
        amount, direction = abs(w), "expense"
    elif d:
        amount, direction = abs(d), "income"
    else:
        return RawTransaction(
            date=parsed.date, merchant_raw=partner or kind, excluded=True,
            exclude_reason="no_amount", raw_text=",".join(row),
        )

    if kind == "チャージ":
        merchant = f"チャージ {method}".strip()
    elif kind in _PAYPAY_KIND_PREFIX:
        prefix = _PAYPAY_KIND_PREFIX[kind]
        merchant = f"{prefix} {partner}".strip() if partner and partner != "PayPay" else prefix
    else:
        merchant = partner or kind

    excluded, reason = False, ""
    if direction == "expense" and _PAYPAY_BY_CARD.search(_nfkc(method)):
        excluded, reason = True, "paid_by_card"

    return RawTransaction(
        date=parsed.date,
        time=time,
        amount=amount,
        merchant_raw=merchant,
        direction=direction,
        confidence=0.95,
        excluded=excluded,
        exclude_reason=reason,
        raw_text=",".join(row),
    )


def _mapped_row(row: list[str], m: ColumnMapping, anchor: dt.date | None) -> RawTransaction | None:
    date_s = _cell(row, m.date)
    merchant = _cell(row, m.merchant)
    parsed = parse_date(date_s, anchor=anchor) if date_s else None

    amount: int | None = None
    direction = "expense"
    if m.withdrawal is not None or m.deposit is not None:
        w = parse_amount(_cell(row, m.withdrawal))
        d = parse_amount(_cell(row, m.deposit))
        if w:
            amount, direction = abs(w), "expense"
        elif d:
            amount, direction = abs(d), "income"
        elif w == 0 or d == 0:
            amount = 0
    elif m.amount is not None:
        a = parse_amount(_cell(row, m.amount))
        if a is not None:
            positive_expense = m.positive_is_expense
            if a >= 0:
                amount, direction = a, ("expense" if positive_expense else "income")
            else:
                amount, direction = -a, ("income" if positive_expense else "expense")

    balance = parse_amount(_cell(row, m.balance)) if m.balance is not None else None
    memo = _cell(row, m.memo) if m.memo is not None else ""

    # 三井住友銀行导出的末尾有一行「2024/3/30,,0,"　",0」占位，金额 0 且无内容
    if (amount is None or amount == 0) and not merchant.strip():
        return RawTransaction(
            date=parsed.date if parsed else None, excluded=True, exclude_reason="no_amount",
            raw_text=",".join(row),
        )
    if parsed is None:
        return RawTransaction(
            merchant_raw=merchant, amount=amount, excluded=True, exclude_reason="no_date",
            raw_text=",".join(row),
        )
    if amount is None:
        return RawTransaction(
            date=parsed.date, merchant_raw=merchant, excluded=True, exclude_reason="no_amount",
            raw_text=",".join(row),
        )

    return RawTransaction(
        date=parsed.date,
        amount=amount,
        merchant_raw=merchant,
        direction=direction,
        confidence=0.95,
        date_inferred=parsed.year_inferred,
        balance_after=balance,
        raw_text=",".join(row) + (f" | {memo}" if memo else ""),
    )


def parse_csv(
    content: bytes,
    filename: str = "",
    mapping_override: ColumnMapping | None = None,
) -> tuple[ExtractResult, Detected, str]:
    """整个文件 → ExtractResult。返回 (结果, 识别信息, 编码)。"""
    text, encoding = decode(content)
    rows = read_rows(text)
    det = detect(rows, filename)

    mapping = mapping_override or det.mapping
    if mapping is None:
        return ExtractResult(warnings=["csv:unknown_format"], provider="csv"), det, encoding

    start = det.data_start if mapping_override is None else (1 if mapping.has_header else 0) + mapping.skip_rows
    anchor = det.statement_month

    out: list[RawTransaction] = []
    if det.profile is RAKUTEN_CARD and mapping_override is None:
        out = _rakuten_card_rows(rows[start:], det.header, anchor)
    else:
        for row in rows[start:]:
            if det.profile is SMBC_CARD and mapping_override is None:
                t = _smbc_card_row(row, anchor)
            elif det.profile is PAYPAY and mapping_override is None:
                t = _paypay_row(row, det.header)
            else:
                t = _mapped_row(row, mapping, anchor)
            if t is not None:
                out.append(t)

    detected_balance = None
    if det.profile is SMBC_BANK:
        # 口座明細按日期降序，首行残高即当前余额
        for t in out:
            if not t.excluded and t.balance_after is not None:
                detected_balance = t.balance_after
                break

    result = ExtractResult(
        transactions=out,
        detected_institution=det.profile.key if det.profile else None,
        detected_balance=detected_balance,
        statement_month=anchor.strftime("%Y-%m") if anchor else None,
        warnings=det.notes,
        provider="csv",
    )
    return result, det, encoding
