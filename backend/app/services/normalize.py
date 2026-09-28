"""Merchant normalization and fingerprints.

Every step must preserve order. Never sort tokens or characters:
ETC round trips differ only in word order and are two real transactions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

_PAYMENT_PREFIXES: tuple[str, ...] = (
    "v/",
    "visa",
    "jcb",
    "mastercard",
    "amex",
    "paypay/",
    "ラクテンペイ",
    "楽天ペイ",
    "d払い",
    "aupay",
    "au pay",
    "ap/qp/",
    "ap/",
    "qp/",
)

_LEADING_VOUCHER = re.compile(r"^v\d{5,}")

_CORPORATE_AFFIXES: tuple[str, ...] = (
    "株式会社",
    "有限会社",
    "合同会社",
    "(株)",
    "(有)",
    "カ)",
    "(カ",
    "ユ)",
    "(ユ",
)

_KATAKANA_HYPHEN = re.compile(r"(?<=[ァ-ヺ])[-\u2010\u2011\u2012\u2013\u2014\u2015]")

_SMALL_KANA = str.maketrans("ァィゥェォヵヶッャュョヮぁぃぅぇぉっゃゅょゎ", "アイウエオカケツヤユヨワあいうえおつやゆよわ")

_TRAILING_PAY_METHOD = re.compile(r"(?:/(?:nfc|id|qp|m)|●|\(applev\))+$")

_BRAND_SEPARATOR = re.compile(r"\s+[-－‐‑–—―]\s+")

_TRAILING_STORE_NO = re.compile(r"\d{3,}$")

_TRAILING_YEAR_MONTH = re.compile(r"(?:\d{4}[/\-.]\d{1,2}|\d{4}年\d{1,2}月?)$")


def normalize_merchant(raw: str) -> str:
    if not raw:
        return ""

    s = unicodedata.normalize("NFKC", raw)

    s = s.lower()

    s = re.sub(r"\s+", "", s)

    s = _KATAKANA_HYPHEN.sub("ー", s)

    s = s.translate(_SMALL_KANA)

    s = _TRAILING_PAY_METHOD.sub("", s)

    s = _LEADING_VOUCHER.sub("", s)
    changed = True
    while changed:
        changed = False
        for prefix in _PAYMENT_PREFIXES:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix) :]
                changed = True

    changed = True
    while changed:
        changed = False
        for affix in _CORPORATE_AFFIXES:
            a = affix.lower()
            if s.startswith(a) and len(s) > len(a):
                s = s[len(a) :]
                changed = True
            if s.endswith(a) and len(s) > len(a):
                s = s[: -len(a)]
                changed = True

    s = _TRAILING_YEAR_MONTH.sub("", s)

    s = _TRAILING_STORE_NO.sub("", s)

    s = s.strip()
    if not s:
        s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).lower()
    return s


def merchant_brand(raw: str) -> str:
    """Brand-level key for learning ("brand - branch"). Not used in fingerprints."""
    if not raw:
        return ""
    head = _BRAND_SEPARATOR.split(raw.strip(), maxsplit=1)[0]
    return normalize_merchant(head) if head else normalize_merchant(raw)


def make_fingerprint(
    date: dt.date | None,
    direction: str,
    amount: int,
    merchant_norm: str,
) -> str:
    parts = [
        date.isoformat() if date else "",
        direction or "",
        str(amount),
        merchant_norm,
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()
