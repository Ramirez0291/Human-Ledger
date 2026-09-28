"""商家名规范化与交易指纹（需求书 F4.1）。

这是去重与分类学习的共同基准。规范化管道的每一步都必须是**保序**的：

    ⚠️ 禁止对词元排序、禁止对字符排序。

理由见需求书附录 A.4.1：楽天カード 同日两条 620 円

        ETCカード売上 ホウライ      ニシイシキリホンセ
        ETCカード売上 ニシイシキリホンセン ホウライ

是高速公路 ETC 的往返两程，是真实的两笔交易。任何无序化处理都会把它们
误判为同一笔并合并掉。

另需注意：merchant_norm 同时服务于「判重」与「商家记忆」，二者对激进程度的
诉求相反——判重要保守（宁可漏合并），学习要激进（希望同一家店都归一起）。
本模块按**判重的保守口径**实现；学习侧的宽松匹配由用户规则（F5.2 第 1 层，
contains / regex）承担。例如 SPOTIFY 每笔带不同交易号，靠一条
"contains SPOTIFY" 规则解决，而不是把规范化写得更激进。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata

# --------------------------------------------------------------------------
# 规则表（可按需扩充；顺序有意义，自上而下依次应用）
# --------------------------------------------------------------------------

# 支付渠道 / 卡组织前缀。这些是刷卡渠道加的，不属于商家本身，
# 去掉后同一家店在不同卡上的记录才能对上。
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
    "ap/qp/",  # iD / QUICPay（原文为全角「ＡＰ／ＱＰ／」，NFKC 后变成此形）
    "ap/",
    "qp/",
)

# 形如「V697418 なか卯/iD」的 iD 传票号前缀（三井住友銀行口座明細）
_LEADING_VOUCHER = re.compile(r"^v\d{5,}")

# 法人格。前后缀都可能出现。
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

# 片假名之后紧跟的连字符（去空白后）。除 ASCII「-」外，卡公司明细里常见
# U+2015「―」（フアミリ―マ―ト）、U+2010「‐」，NFKC 都不会把它们变成长音。
_KATAKANA_HYPHEN = re.compile(r"(?<=[ァ-ヺ])[-\u2010\u2011\u2012\u2013\u2014\u2015]")

# 小写假名 → 普通假名。卡公司明细不分大小（ミニストツプ / フアミリ）而 App 截图分，
# 同一家店在两种来源里对不上。只用于比对基准，不影响显示。
_SMALL_KANA = str.maketrans("ァィゥェォヵヶッャュョヮぁぃぅぇぉっゃゅょゎ", "アイウエオカケツヤユヨワあいうえおつやゆよわ")

# 末尾的支付方式标记：三井住友カード 明细里的「／ＮＦＣ」「／ｉＤ」「／ＱＰ」，
# Apple Pay 的「●」。同一家店走不同方式刷会带不同后缀。
_TRAILING_PAY_METHOD = re.compile(r"(?:/(?:nfc|id|qp|m)|●|\(applev\))+$")

# PayPay 取引先写作「ブランド - 店舗名」；截取品牌部分作为学习用的宽松键
_BRAND_SEPARATOR = re.compile(r"\s+[-－‐‑–—―]\s+")

# 末尾店铺编号：3 位以上纯数字（含被空格分隔的情况，空格此时已被去除）
_TRAILING_STORE_NO = re.compile(r"\d{3,}$")

# 末尾的年月标记，如「関西電力電気2026/09」「東京ガス2026年9月」。
# 不去掉的话，同一项公共事业每个月都会成为一个新商家，商家记忆永远学不会。
_TRAILING_YEAR_MONTH = re.compile(r"(?:\d{4}[/\-.]\d{1,2}|\d{4}年\d{1,2}月?)$")


def normalize_merchant(raw: str) -> str:
    """把商家名原文规范化为比对基准。

    步骤：
      1. NFKC 正规化（全角→半角、半角片假名→全角片假名）
      2. 转小写
      3. 去除全部空白（含全角空格，NFKC 后已成半角空格）
      4. 剥离支付渠道前缀
      5. 剥离法人格前后缀
      6. 剥离末尾年月标记
      7. 剥离末尾店铺编号

    每一步都保持字符顺序不变。
    """
    if not raw:
        return ""

    # 1. NFKC：ＡＭＡＺＯＮ→AMAZON、ﾀﾞｲｿｰ→ダイソー、＼u3000→半角空格、／→/
    s = unicodedata.normalize("NFKC", raw)

    # 2. 大小写归一
    s = s.lower()

    # 3. 去除所有空白字符
    s = re.sub(r"\s+", "", s)

    # 3b. 半角片假名里的长音常被写成 ASCII 连字符（銀行 CSV：ｶ-ﾄﾞｻ-ﾋﾞｽ）。
    #     NFKC 后成为「カ-ドサ-ビス」，对不上词典与其它来源里的「カードサービス」。
    #     片假名之后的「-」归一为「ー」；数字/字母间的连字符（如 J-WEST）不动。
    s = _KATAKANA_HYPHEN.sub("ー", s)

    # 3c. 小写假名归一：ミニストツプ = ミニストップ
    s = s.translate(_SMALL_KANA)

    # 3d. 末尾支付方式标记
    s = _TRAILING_PAY_METHOD.sub("", s)

    # 4. 支付渠道前缀（可能叠加，循环剥离）
    s = _LEADING_VOUCHER.sub("", s)
    changed = True
    while changed:
        changed = False
        for prefix in _PAYMENT_PREFIXES:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix) :]
                changed = True

    # 5. 法人格前后缀
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

    # 6. 末尾年月
    s = _TRAILING_YEAR_MONTH.sub("", s)

    # 7. 末尾店铺编号
    s = _TRAILING_STORE_NO.sub("", s)

    s = s.strip()
    if not s:
        # 全部被剥掉（如银行明细里的「V000000」）：退回到最朴素的形式，
        # 空字符串会让所有这类行指纹相同、互相判成重复
        s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).lower()
    return s


def merchant_brand(raw: str) -> str:
    """学习用的宽松键：品牌级别的规范化名。

    PayPay 的取引先写成「一蘭 - 一蘭 新宿店」「ロフト - 渋谷ロフト」，
    分隔符前是品牌。按品牌记忆一次，同品牌其他分店就都能预填。
    没有分隔符时与 normalize_merchant 相同。**不参与指纹**——不同分店仍是不同交易。
    """
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
    """交易指纹：判重的主键（需求书 F4.1）。

    日期参与计算，因此同商家同金额但不同日期的两笔不会被判为重复——
    这正是 Olive 样本中 09/01 与 09/02 两笔 230 円 ミニストップ 的正确结果
    （它们会落到 L3b 模糊匹配的「可能重复」黄标，而非直接判重）。
    """
    parts = [
        date.isoformat() if date else "",
        direction or "",
        str(amount),
        merchant_norm,
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    """两个已规范化商家名的相似度，用于 L3b 模糊匹配（0.0–1.0）。

    使用 SequenceMatcher 而非编辑距离比值：它基于最长公共子序列块，
    对「同一商家名多出一段店铺后缀」这类差异更宽容，而对词序颠倒
    （ETC 往返两程）给出的分数更低——正是此处需要的偏向。
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()
