"""日元金额解析（需求书 F3.3 / 附录 A.3.4）。

支持：
    ¥1,234  ￥1,234  \\1,234  1,234円  1234  ¥ 620（符号后有空格）
    △1,234  ▲1,234  -1,234  −1,234  (1,234)      → 负数
    １，２３４（全角）                              → NFKC 归一
    行尾「+」「−」方向标记（三井住友銀行）

日元无小数。含小数点的数字（如 イデミツ 那行的「0.00」）**不是金额**，
可作为排除判据（附录 A.2.3）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 负号家族：ASCII 减号、Unicode 减号、全角减号、日式三角
_NEG = r"[-−－△▲]"
_CURRENCY = r"(?:[¥￥\\]|JPY)?"

# 主模式：可选负号 → 可选货币符 → 数字（允许千分位）→ 可选「円」
# (?<![\d.]) 与 (?![\d.]) 保证不把 "0.00" 或 "2026.09" 的一部分当成金额
_AMOUNT = re.compile(
    rf"(?P<paren>\()?"
    rf"(?P<neg>{_NEG})?\s*"
    rf"{_CURRENCY}\s*"
    rf"(?P<neg2>{_NEG})?\s*"
    # 数字前后都不能再接数字（防止从「26.09.07」里抠出「2」），
    # 也不能接「.数字」或「,数字」（防止把小数或未完整匹配的千分位切一半）
    rf"(?<![\d.,])(?P<num>\d{{1,3}}(?:,\d{{3}})+|\d+)(?!\d|[.,]\d)"
    rf"\s*(?:円|JPY)?"
    rf"(?(paren)\))"
)

# 行尾方向标记（三井住友銀行「2,402 円 +」「41,208 円 −」）
_TRAILING_SIGN = re.compile(r"(?:円|¥)?\s*(?P<sign>[+＋]|[-−－])\s*$")

# 「残高 50,073 円」：紧跟在残高标签后的金额是交易后余额，不是交易金额
_BALANCE_LABEL = re.compile(r"(残高|預金残高|お預り残高|口座残高)\s*[:：]?\s*")


@dataclass
class ParsedAmount:
    value: int  # 绝对值
    negative: bool  # 原文带负号 / 三角 / 括号
    span: tuple[int, int]
    # 该金额前面紧跟「残高」标签
    is_balance: bool = False
    # 带 ¥ / 円 / 千分位 / 负号；不带的裸数字只在独占一行时才被接受
    marked: bool = True


def normalize_text(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _has_decimal(s: str, span: tuple[int, int]) -> bool:
    """金额后紧跟「.digits」即视为小数——日元无小数，此类不是交易金额。"""
    tail = s[span[1] : span[1] + 4]
    return bool(re.match(r"\.\d", tail))


def parse_amounts(text: str) -> list[ParsedAmount]:
    """找出文本中所有金额，按出现顺序返回。

    裸数字（无 ¥ / 円 / 千分位）只有在**独占一行**时才视为金额。日本金融 App
    显示金额时一定带 円 或 ¥；嵌在文字里的裸数字是店铺编号、丁目、支店号
    （「日本橋3丁目」「ENEOS 99993 6342」「支店 3396840」），不是金额。
    """
    s = normalize_text(text)
    stripped = s.strip()
    out: list[ParsedAmount] = []
    for m in _AMOUNT.finditer(s):
        if _has_decimal(s, m.span()):
            continue
        num = m["num"].replace(",", "")
        if not num:
            continue
        raw = m.group(0)
        marked = ("," in raw) or ("円" in raw) or ("¥" in raw) or ("JPY" in raw) or bool(m["neg"] or m["neg2"] or m["paren"])
        if not marked and raw.strip() != stripped:
            continue
        negative = bool(m["neg"] or m["neg2"] or m["paren"])

        # 判断是否为残高
        prefix = s[max(0, m.start() - 12) : m.start()]
        is_balance = bool(_BALANCE_LABEL.search(prefix))

        out.append(
            ParsedAmount(
                value=int(num),
                negative=negative,
                span=m.span(),
                is_balance=is_balance,
                marked=marked,
            )
        )
    return out


def parse_amount(text: str) -> int | None:
    """解析单个金额（用于 CSV 单元格）。空、「-」、「−」视为无值。"""
    s = normalize_text(text).strip()
    if not s or s in {"-", "−", "－", "—"}:
        return None
    found = [a for a in parse_amounts(s) if not a.is_balance]
    if not found:
        return None
    a = found[0]
    return -a.value if a.negative else a.value


def trailing_sign(text: str) -> str | None:
    """行尾的「+」/「−」方向标记，返回 "income" / "expense" / None。"""
    s = normalize_text(text).rstrip()
    m = _TRAILING_SIGN.search(s)
    if not m:
        return None
    return "income" if m["sign"] in "+＋" else "expense"


def blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """把指定片段替换为**等长**空白。

    等长是关键：后续还要按其它 token 的 span 继续剔除，若长度变化，
    那些 span 的偏移就全部错位。
    """
    s = list(text)
    for start, end in spans:
        for i in range(start, min(end, len(s))):
            s[i] = " "
    return "".join(s)
