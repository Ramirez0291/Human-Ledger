from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_NEG = r"[-−－△▲]"
_CURRENCY = r"(?:[¥￥\\]|JPY)?"

_AMOUNT = re.compile(
    rf"(?P<paren>\()?"
    rf"(?P<neg>{_NEG})?\s*"
    rf"{_CURRENCY}\s*"
    rf"(?P<neg2>{_NEG})?\s*"
    rf"(?<![\d.,])(?P<num>\d{{1,3}}(?:,\d{{3}})+|\d+)(?!\d|[.,]\d)"
    rf"\s*(?:円|JPY)?"
    rf"(?(paren)\))"
)

_TRAILING_SIGN = re.compile(r"(?:円|¥)?\s*(?P<sign>[+＋]|[-−－])\s*$")

_BALANCE_LABEL = re.compile(r"(残高|預金残高|お預り残高|口座残高)\s*[:：]?\s*")


@dataclass
class ParsedAmount:
    value: int
    negative: bool
    span: tuple[int, int]
    is_balance: bool = False
    marked: bool = True


def normalize_text(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _has_decimal(s: str, span: tuple[int, int]) -> bool:
    tail = s[span[1] : span[1] + 4]
    return bool(re.match(r"\.\d", tail))


def parse_amounts(text: str) -> list[ParsedAmount]:
    """Bare numbers count as amounts only when alone on a line."""
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
    s = normalize_text(text).strip()
    if not s or s in {"-", "−", "－", "—"}:
        return None
    found = [a for a in parse_amounts(s) if not a.is_balance]
    if not found:
        return None
    a = found[0]
    return -a.value if a.negative else a.value


def trailing_sign(text: str) -> str | None:
    s = normalize_text(text).rstrip()
    m = _TRAILING_SIGN.search(s)
    if not m:
        return None
    return "income" if m["sign"] in "+＋" else "expense"


def blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Same-length replacement keeps other spans valid."""
    s = list(text)
    for start, end in spans:
        for i in range(start, min(end, len(s))):
            s[i] = " "
    return "".join(s)
