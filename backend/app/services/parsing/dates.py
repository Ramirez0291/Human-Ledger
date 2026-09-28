"""日本金融 App 与 CSV 中出现的日期格式解析（需求书 F3.3 / 附录 A.3.2）。

支持：
    2026/09/07  2026-09-07  2026.09.07  2026年9月7日  20260907
    26.09.02    26/09/02                            （两位年份，Olive / 三井住友銀行）
    令和8年9月7日  R8.9.7                              （和历）
    9/7  09/07  9月7日                                 （无年份，J-WEST）
    以上均可带星期「(月)」与时刻「21時56分」「21:56」后缀
    全角数字「２０２６／０９／０７」先经 NFKC 归一

无年份日期的年份推断是最容易出错的地方，规则见 infer_year()。
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass

# 和历元年对应的西历年份 − 1（令和元年 = 2019）
_ERA_BASE = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925}

_WEEKDAY = r"(?:\s*[(（][月火水木金土日][)）])?"
# 时刻：21時56分 / 21:56 / 21時
_TIME = r"(?:\s*(?P<hour>\d{1,2})\s*[時:]\s*(?P<minute>\d{1,2})?\s*分?)?"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "full",
        re.compile(
            r"(?P<y>\d{4})\s*[/\-.年]\s*(?P<m>\d{1,2})\s*[/\-.月]\s*(?P<d>\d{1,2})\s*日?" + _WEEKDAY + _TIME
        ),
    ),
    ("compact", re.compile(r"(?<!\d)(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})(?!\d)")),
    (
        "era",
        re.compile(
            r"(?P<era>令和|平成|昭和|[RHS])\s*(?P<ey>元|\d{1,2})\s*[年.]\s*(?P<m>\d{1,2})\s*[月.]\s*(?P<d>\d{1,2})\s*日?"
            + _WEEKDAY
            + _TIME
        ),
    ),
    (
        "short_year",
        re.compile(r"(?<!\d)(?P<y>\d{2})\s*[/.\-]\s*(?P<m>\d{1,2})\s*[/.\-]\s*(?P<d>\d{1,2})(?!\d)" + _WEEKDAY + _TIME),
    ),
    (
        "no_year",
        re.compile(r"(?<![\d/.\-])(?P<m>\d{1,2})\s*[/月]\s*(?P<d>\d{1,2})\s*日?(?![\d/.\-])" + _WEEKDAY + _TIME),
    ),
]

_YEAR_MONTH = re.compile(r"(?<!\d)(?P<y>\d{4})\s*[/\-.年]\s*(?P<m>\d{1,2})\s*月?(?![\d/])")


@dataclass
class ParsedDate:
    date: dt.date
    time: dt.time | None
    # 年份来自推断而非原文（附录 A.3.2），UI 需标注
    year_inferred: bool
    # 匹配到的原文片段，用于从行文本中剔除
    span: tuple[int, int]
    kind: str


def normalize_text(s: str) -> str:
    """NFKC：全角数字/符号 → 半角，便于统一匹配。"""
    return unicodedata.normalize("NFKC", s)


def infer_year(month: int, day: int, anchor: dt.date | None, today: dt.date | None = None) -> int:
    """为无年份日期推断年份（附录 A.3.2）。

    anchor 为「支払月」等锚点（如信用卡明细页的「8月」Tab）。信用卡消费日通常
    早于支払月 0–2 个月，因此：消费月 ≤ 锚点月 → 同年；消费月 > 锚点月 → 上一年
    （覆盖 1 月支払 ↔ 11/12 月消费的跨年情形）。

    无锚点时取不晚于今天的最近一个同月日。
    """
    if anchor is not None:
        return anchor.year if month <= anchor.month else anchor.year - 1

    today = today or dt.date.today()
    candidate = _safe_date(today.year, month, day)
    if candidate is not None and candidate <= today:
        return today.year
    return today.year - 1


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _time_of(m: re.Match[str]) -> dt.time | None:
    h = m.groupdict().get("hour")
    if h is None:
        return None
    minute = m.groupdict().get("minute")
    try:
        return dt.time(int(h), int(minute) if minute else 0)
    except ValueError:
        return None


def parse_date(
    text: str,
    anchor: dt.date | None = None,
    today: dt.date | None = None,
) -> ParsedDate | None:
    """从一段文本中找出第一个日期。找不到返回 None。

    anchor：年份推断锚点，通常来自页面上的年月标题或支払月 Tab。
    """
    s = normalize_text(text)

    for kind, pat in _PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        g = m.groupdict()
        month = int(g["m"])
        day = int(g["d"])
        inferred = False

        if kind in ("full", "compact"):
            year = int(g["y"])
        elif kind == "era":
            ey = 1 if g["ey"] == "元" else int(g["ey"])
            era = g["era"]
            year = _ERA_BASE[era] + ey
        elif kind == "short_year":
            year = 2000 + int(g["y"])
        else:  # no_year
            year = infer_year(month, day, anchor, today)
            inferred = True

        date = _safe_date(year, month, day)
        if date is None:
            continue
        return ParsedDate(
            date=date,
            time=_time_of(m),
            year_inferred=inferred,
            span=m.span(),
            kind=kind,
        )

    return None


def parse_year_month(text: str) -> dt.date | None:
    """识别「2026年10月」「2026.09」「2026/09」这类年月标题，返回该月 1 日。

    用作后续无年份 / 两位年份日期的推断锚点。整行只含年月时才算标题，
    避免把「2026/09/07」这种完整日期误认为标题。
    """
    s = normalize_text(text).strip()
    m = _YEAR_MONTH.fullmatch(s) or _YEAR_MONTH.fullmatch(s.rstrip("分"))
    if not m:
        return None
    y, mo = int(m["y"]), int(m["m"])
    return _safe_date(y, mo, 1)


def parse_month_only(text: str) -> int | None:
    """识别「8月」这类仅有月份的支払月标签，返回月份数。"""
    s = normalize_text(text).strip()
    m = re.fullmatch(r"(?P<m>\d{1,2})月(?:分|支払分|お支払い分)?", s)
    if not m:
        return None
    mo = int(m["m"])
    return mo if 1 <= mo <= 12 else None
