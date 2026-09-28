from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app.services.ocr.base import ExtractResult, RawTransaction
from app.services.parsing.amounts import (
    normalize_text,
    blank_spans,
    parse_amounts,
    trailing_sign,
)
from app.services.parsing.dates import (
    parse_date,
    parse_month_only,
    parse_year_month,
)

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

_IGNORE_LINE = re.compile(
    r"^(?:"
    r"利用明細|ご利用明細|取引履歴|お支払明細|明細|すべて|残高|残高カード|"
    r"クレジット|デビット|ポイント払い|他のカードを選択|変更する|"
    r"今月のお支払金額を調整する|詳細を見る|絞り込み|新しい順|古い順|家計簿に保存|"
    r"ホーム|口座一覧|振込・振替|資産管理|メニュー|キャンペーン|ポイントUP|"
    r"お得な情報|その他|おすすめ情報|支払調整|PayPay残高|PayPayカード|"
    r"\d{1,2}:\d{2}|"
    r"[<>‹›＜＞〈〉?？]+"
    r")$"
)

_SUMMARY = re.compile(
    r"^(?:"
    r"ご請求内訳|通常|リボ|分割|事前お支払額|お支払い金額|お支払金額|お支払い額|"
    r"合計|ご利用金額合計|今月のお支払金額|預金残高|お支払可能金額|請求額|ご請求額|"
    r"利用可能額|ご利用可能額|お支払い予定額"
    r")(?:[(（].*?[)）])?$"
)

_STATUS_FAILED = re.compile(r"支払い?失敗|決済失敗|キャンセル|取消|取り消し|失効")
_STATUS_REFUND = re.compile(r"返金|払い?戻し|返品")
_STATUS_OK = re.compile(r"支払い?完了|決済完了|完了")

_STRIP_TOKENS = [
    re.compile(r"\d+\s*回払い?"),
    re.compile(r"ボーナス(?:払い|一括)?"),
    re.compile(r"リボ払い"),
    re.compile(r"分割払い"),
    re.compile(r"(?<![\d/.\-])\d{1,2}:\d{2}(?!\d)"),
    re.compile(r"支払い?完了|決済完了"),
    re.compile(r"[(（]未確定[)）]"),
    re.compile(r"現在"),
]

_STRIP_AFTER_AMOUNTS = [
    re.compile(r"(?<![぀-ヿ一-鿿])(?:PayPay)?残高(?:カード)?(?![぀-ヿ一-鿿])"),
    re.compile(r"(?<![\d.])\d+\.\d+(?![\d.])"),
]

_INSTALLMENT = re.compile(r"分割\s*(?P<total>\d+)\s*回払い?\s*[(（]\s*(?P<cur>\d+)\s*回目\s*[)）]")
_LABELED_TOTAL = re.compile(r"(?:ご利用金額|利用金額|お買上げ金額)\s*[:：]?\s*")

_INCOME_WORDS = re.compile(r"入金|預入|給与|給料|賞与|還付|受取|振込入金|利息")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


@dataclass
class _Block:
    lines: list[str] = field(default_factory=list)
    merchant_parts: list[str] = field(default_factory=list)
    amount: int | None = None
    amount_negative: bool = False
    date: dt.date | None = None
    time: dt.time | None = None
    year_inferred: bool = False
    direction: str | None = None
    balance_after: int | None = None
    excluded: bool = False
    exclude_reason: str = ""
    installment: dict | None = None
    labeled_total: int | None = None
    saw_meta: bool = False

    @property
    def merchant(self) -> str:
        return " ".join(p for p in self.merchant_parts if p).strip()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


def parse_lines(
    text: str,
    *,
    statement_month: dt.date | None = None,
    today: dt.date | None = None,
    default_direction: str = "expense",
) -> ExtractResult:
    today = today or dt.date.today()
    anchor: dt.date | None = statement_month
    detected_balance: int | None = None
    warnings: list[str] = []

    blocks: list[_Block] = []
    current: _Block | None = None

    def close() -> None:
        nonlocal current
        if current is not None and (current.merchant_parts or current.amount is not None):
            blocks.append(current)
        current = None

    for raw_line in text.splitlines():
        line = normalize_text(raw_line).strip()
        if not line:
            continue
        if _IGNORE_LINE.match(line):
            continue

        ym = parse_year_month(line)
        if ym is not None:
            if statement_month is None:
                anchor = ym
            close()
            continue
        mo = parse_month_only(line)
        if mo is not None:
            if statement_month is None:
                year = (anchor or today).year
                anchor = dt.date(year, mo, 1)
            close()
            continue

        parsed_date = parse_date(line, anchor=anchor, today=today)
        work = blank_spans(line, [parsed_date.span]) if parsed_date else line

        installment = _INSTALLMENT.search(work)
        if installment:
            work = blank_spans(work, [installment.span()])

        summary_probe = re.sub(r"\s+", " ", re.sub(r"[¥￥\]?\s*[\d,]+\s*円?", " ", work)).strip(" ・:：-−")
        is_summary = bool(summary_probe) and bool(_SUMMARY.match(summary_probe))

        had_label = False
        for pat in _STRIP_TOKENS:
            work, n = pat.subn(lambda m: " " * len(m.group(0)), work)
            had_label = had_label or n > 0

        amounts = parse_amounts(work)
        balance_vals = [a for a in amounts if a.is_balance]
        txn_amounts = [a for a in amounts if not a.is_balance]

        labeled_total: int | None = None
        labeled_total_match = _LABELED_TOTAL.search(work)
        if labeled_total_match and txn_amounts:
            after = [
                a
                for a in txn_amounts
                if a.span[0] >= labeled_total_match.start() and a.span[1] > labeled_total_match.end()
            ]
            if after:
                labeled_total = after[0].value
                txn_amounts = [a for a in txn_amounts if a is not after[0]]

        sign = trailing_sign(work)
        failed = bool(_STATUS_FAILED.search(work))
        refund = bool(_STATUS_REFUND.search(work))

        residual = blank_spans(work, [a.span for a in amounts])
        residual = _LABELED_TOTAL.sub(" ", residual)
        residual = _STATUS_FAILED.sub(" ", residual)
        residual = _STATUS_REFUND.sub(" ", residual)
        residual = _STATUS_OK.sub(" ", residual)
        for pat in _STRIP_AFTER_AMOUNTS:
            residual = pat.sub(" ", residual)
        residual = re.sub(r"(?:円|¥|JPY)", " ", residual)
        residual = re.sub(r"\s*[+＋\-−－]\s*$", "", residual)
        residual = re.sub(r"\s+", " ", residual).strip(" ・:：-−")

        has_text = bool(residual)
        has_amount = bool(txn_amounts)
        has_date = parsed_date is not None
        token_only = not has_text and (
            has_amount
            or has_date
            or balance_vals
            or failed
            or refund
            or installment
            or labeled_total is not None
        )

        if not has_text and not token_only:
            if had_label and current is not None:
                current.saw_meta = True
            continue

        if is_summary:
            close()
            current = _Block(
                lines=[line], merchant_parts=[summary_probe], excluded=True, exclude_reason="summary_row"
            )
            current.saw_meta = True
            if txn_amounts:
                current.amount = txn_amounts[0].value
            if detected_balance is None and re.match(r"^(?:預金残高|口座残高)", summary_probe) and txn_amounts:
                detected_balance = txn_amounts[0].value
            continue

        if current is not None and current.excluded and current.exclude_reason == "summary_row":
            if not has_text and has_amount and current.amount is None:
                current.amount = txn_amounts[0].value
                if detected_balance is None and re.match(r"^(?:預金残高|口座残高)", current.merchant):
                    detected_balance = current.amount
                continue
            close()

        if (
            not has_text
            and has_amount
            and not txn_amounts[0].marked
            and current is not None
            and current.merchant_parts
            and current.amount is not None
            and not current.saw_meta
        ):
            residual = work.strip()
            has_text = True
            txn_amounts = []
            has_amount = False

        if has_text:
            if current is not None and not current.merchant_parts and current.amount is not None:
                current.excluded = True
                current.exclude_reason = "orphan_amount"
                close()
            is_continuation = (
                current is not None
                and bool(current.merchant_parts)
                and not current.saw_meta
                and not has_date
                and not has_amount
            )
            if current is None or (current.merchant_parts and not is_continuation):
                close()
                current = _Block()
            current.merchant_parts.append(residual)
        else:
            if current is None:
                current = _Block()

        current.lines.append(line)

        if txn_amounts and current.amount is None:
            a = txn_amounts[0]
            current.amount = a.value
            current.amount_negative = a.negative
        if labeled_total is not None:
            current.labeled_total = labeled_total
        if balance_vals:
            current.balance_after = balance_vals[-1].value
            if detected_balance is None:
                detected_balance = balance_vals[-1].value
        if parsed_date:
            current.saw_meta = True
            if current.date is None:
                current.date = parsed_date.date
                current.time = parsed_date.time
                current.year_inferred = parsed_date.year_inferred
        if had_label:
            current.saw_meta = True
        if sign and current.direction is None:
            current.direction = sign
        if refund:
            current.direction = "income"
        if failed:
            current.excluded = True
            current.exclude_reason = "payment_failed"
        if installment:
            current.installment = {
                "total_times": int(installment["total"]),
                "current_time": int(installment["cur"]),
            }

    close()

    results: list[RawTransaction] = []
    last_date: dt.date | None = None
    last_time: dt.time | None = None

    for blk in blocks:
        merchant = blk.merchant
        date_inferred = blk.year_inferred
        date = blk.date
        time = blk.time

        if not blk.excluded:
            if date is None and last_date is not None:
                date = last_date  # A.3.1
                time = None
                date_inferred = True
            elif date is not None:
                last_date, last_time = date, time

        amount = blk.amount
        installment = blk.installment
        if installment is not None:
            if blk.labeled_total is not None:
                installment["total_amount"] = blk.labeled_total
            if amount is None and blk.labeled_total is not None:
                amount = round(blk.labeled_total / installment["total_times"])
                installment["estimated"] = True
                warnings.append(f"installment_estimated:{merchant}")

        direction = blk.direction
        if direction is None:
            if blk.amount_negative:
                direction = "expense"
            elif _INCOME_WORDS.search(merchant):
                direction = "income"
            else:
                direction = default_direction

        confidence = 0.9
        if blk.excluded:
            confidence = 0.0
        else:
            if date is None:
                confidence -= 0.3
            elif date_inferred:
                confidence -= 0.2
            if amount is None:
                confidence -= 0.4
            if not merchant:
                confidence -= 0.2
        confidence = max(0.0, round(confidence, 2))

        excluded = blk.excluded
        reason = blk.exclude_reason
        if not excluded and amount is None:
            excluded, reason = True, "no_amount"
        if not excluded and not merchant:
            excluded, reason = True, "no_merchant"

        results.append(
            RawTransaction(
                date=date,
                time=time,
                amount=amount,
                merchant_raw=merchant,
                direction=direction,
                confidence=confidence,
                date_inferred=date_inferred,
                excluded=excluded,
                exclude_reason=reason,
                balance_after=blk.balance_after,
                installment=installment,
                raw_text="\n".join(blk.lines),
            )
        )

    return ExtractResult(
        transactions=results,
        detected_balance=detected_balance,
        statement_month=anchor.strftime("%Y-%m") if anchor else None,
        warnings=warnings,
        provider="text",
    )
