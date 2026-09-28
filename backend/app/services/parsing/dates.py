from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass

_ERA_BASE = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925}

_WEEKDAY = r"(?:\s*[(（][月火水木金土日][)）])?"
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
    year_inferred: bool
    span: tuple[int, int]
    kind: str


def normalize_text(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def infer_year(month: int, day: int, anchor: dt.date | None, today: dt.date | None = None) -> int:
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
    s = normalize_text(text).strip()
    m = _YEAR_MONTH.fullmatch(s) or _YEAR_MONTH.fullmatch(s.rstrip("分"))
    if not m:
        return None
    y, mo = int(m["y"]), int(m["m"])
    return _safe_date(y, mo, 1)


def parse_month_only(text: str) -> int | None:
    s = normalize_text(text).strip()
    m = re.fullmatch(r"(?P<m>\d{1,2})月(?:分|支払分|お支払い分)?", s)
    if not m:
        return None
    mo = int(m["m"])
    return mo if 1 <= mo <= 12 else None
