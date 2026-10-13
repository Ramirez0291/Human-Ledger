"""预算与月末预测（需求书 F7）。

口径
----
- **已花**：本月全部支出（含标了「不计入月度分析」的一次性开支）——预算管的是真实花出去的钱。
  计划内的额外开销用「特别预算」提前加额度，而不是事后把它从预算里拿掉。
- **习惯**：预测只看平时怎么花，一次性开支（exclude_from_analysis）不进历史，也不参与本月节奏。
- 转账（信用卡还款、充值、取现）不是支出，天然不在内。

预测
----
取本月之前最多 6 个「有记录的完整月份」，把每个月按**日历日**摊成逐日支出（31 日在小月里并到月末）。
按日历日而不是按比例对齐，房租、订阅、水电这些固定日扣款才会落在同一天。

    往常同期   = 历史各月第 1..d 天的平均
    往常余下   = 历史各月第 d+1..N 天，逐月一个值
    节奏倍数   = 本月第 1..d 天（不含除外）/ 往常同期，截在 0.5–2 之间，
                 再按已过天数的比例收敛到 1——月初那几天说明不了什么
    预测月末   = 已花 + 平均(往常余下) × 节奏倍数
    区间       = 往常余下的 25% / 75% 分位 × 节奏倍数

没有历史时退回线性外推（已花 ÷ 已过天数 × 当月天数）。
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import CategoryType, Direction
from app.db.models import Budget, Category, SpecialBudget, Transaction
from app.services.reports import _category_names, month_bounds, shift_month

HISTORY_MONTHS = 6
LOOKBACK_MONTHS = 12
PACE_MIN, PACE_MAX = 0.5, 2.0


# --------------------------------------------------------------------------
# 纯计算：不碰数据库，方便单测
# --------------------------------------------------------------------------


@dataclass
class Forecast:
    spent: int
    projected: int
    low: int
    high: int
    pace_ratio: float | None
    basis_months: int
    # 第 1..N 天末的累计：前 elapsed 天是实际，之后是预测
    path: list[int] = field(default_factory=list)


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def fold_days(daily: list[int], n: int) -> list[int]:
    """把一个月的逐日支出按日历日对到 n 天的月份：多出来的 29–31 日并到最后一天。"""
    out = [0] * n
    for i, v in enumerate(daily):
        out[min(i, n - 1)] += v
    return out


def forecast(
    n: int,
    elapsed: int,
    actual: list[int],
    habitual: list[int],
    history: list[list[int]],
) -> Forecast:
    """
    n         本月天数
    elapsed   已过天数（含今天）；整月过完 = n，还没开始 = 0
    actual    本月逐日支出（全部，长度 n）
    habitual  本月逐日支出（不含除外，长度 n）
    history   历史各月逐日支出（不含除外），各自长度为那个月的天数
    """
    d = max(0, min(elapsed, n))
    spent = sum(actual[:d])
    now = sum(habitual[:d])
    folded = [fold_days(h, n) for h in history]

    cumulative: list[int] = []
    run = 0
    for v in actual[:d]:
        run += v
        cumulative.append(run)

    if d == n:
        return Forecast(spent, spent, spent, spent, None, len(folded), cumulative)

    if not folded:
        rate = now / d if d else 0.0
        projected = round(spent + rate * (n - d))
        path = cumulative + [round(spent + rate * (j - d + 1)) for j in range(d, n)]
        return Forecast(spent, projected, projected, projected, None, 0, path)

    before = [sum(h[:d]) for h in folded]
    after = [sum(h[d:]) for h in folded]
    mean_before = sum(before) / len(before)

    ratio: float | None = None
    factor = 1.0
    if d > 0 and mean_before > 0:
        ratio = now / mean_before
        clamped = min(PACE_MAX, max(PACE_MIN, ratio))
        factor = 1 + (clamped - 1) * (d / n)

    scaled = [a * factor for a in after]
    projected = round(spent + sum(scaled) / len(scaled))
    low = round(spent + _quantile(scaled, 0.25))
    high = round(spent + _quantile(scaled, 0.75))

    # 预测路径沿用往常的逐日形状：固定日扣款会在那一天跳一下
    profile = [sum(h[j] for h in folded) / len(folded) * factor for j in range(n)]
    path = list(cumulative)
    acc = float(spent)
    for j in range(d, n):
        acc += profile[j]
        path.append(round(acc))
    if path:
        path[-1] = projected
    return Forecast(spent, projected, low, high, ratio, len(folded), path)


def judge(budget: int | None, spent: int, fc: Forecast, threshold_pct: int, finished: bool) -> str:
    """none / on_track / at_risk / likely_exceed / will_exceed / over"""
    if budget is None:
        return "none"
    if spent > budget:
        return "over"
    if finished:
        return "on_track"
    if fc.low > budget:
        return "will_exceed"
    if fc.projected > budget:
        return "likely_exceed"
    if fc.high > budget or spent * 100 >= budget * threshold_pct:
        return "at_risk"
    return "on_track"


def allocate(amount: int, date_from: dt.date, date_to: dt.date, start: dt.date, end: dt.date) -> int:
    """特别预算按天数摊到 [start, end) 这个月的份额。"""
    lo = max(date_from, start)
    hi = min(date_to, end - dt.timedelta(days=1))
    if hi < lo:
        return 0
    total = (date_to - date_from).days + 1
    return round(amount * ((hi - lo).days + 1) / total)


# --------------------------------------------------------------------------
# 取数
# --------------------------------------------------------------------------


@dataclass
class _Row:
    date: dt.date
    amount: int
    category_id: int | None
    flagged: bool


def _expenses(db: Session, user_id: int, start: dt.date, end: dt.date) -> list[_Row]:
    rows = db.execute(
        select(Transaction.date, Transaction.amount, Transaction.category_id, Transaction.exclude_from_analysis).where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.direction == Direction.expense,
            Transaction.date >= start,
            Transaction.date < end,
        )
    ).all()
    return [_Row(d, a, c, bool(f)) for d, a, c, f in rows]


def _history_months(db: Session, user_id: int, ym: str, rows: list[_Row]) -> list[str]:
    """ym 之前、有记录的完整月份，最近的至多 6 个。

    开始记账的那个月若不是从月初记起（第 4 天以后才有第一笔），数据残缺，不算。
    """
    first = db.execute(
        select(func.min(Transaction.date)).where(
            Transaction.user_id == user_id, Transaction.deleted_at.is_(None)
        )
    ).scalar()
    if first is None:
        return []
    active = {r.date.strftime("%Y-%m") for r in rows}
    first_ym = first.strftime("%Y-%m")
    out = []
    for k in range(1, LOOKBACK_MONTHS + 1):
        m = shift_month(ym, -k)
        if m < first_ym:
            break
        if m == first_ym and first.day > 3:
            continue
        if m in active:
            out.append(m)
        if len(out) == HISTORY_MONTHS:
            break
    return out


def _scopes(db: Session, user_id: int, category_ids: set[int]) -> dict[int, set[int]]:
    """类目 → 它自己加全部子类。"""
    if not category_ids:
        return {}
    children: dict[int, set[int]] = defaultdict(set)
    for cid, parent in db.execute(
        select(Category.id, Category.parent_id).where(Category.user_id == user_id, Category.parent_id.is_not(None))
    ).all():
        children[parent].add(cid)
    return {c: {c, *children.get(c, set())} for c in category_ids}


def _daily(rows: list[_Row], ym: str, n: int, scope: set[int] | None, habitual: bool) -> list[int]:
    out = [0] * n
    for r in rows:
        if r.date.strftime("%Y-%m") != ym:
            continue
        if scope is not None and r.category_id not in scope:
            continue
        if habitual and r.flagged:
            continue
        out[r.date.day - 1] += r.amount
    return out


def _days(ym: str) -> int:
    y, m = (int(x) for x in ym.split("-"))
    return calendar.monthrange(y, m)[1]


def _elapsed(ym: str, today: dt.date) -> int:
    cur = today.strftime("%Y-%m")
    if ym < cur:
        return _days(ym)
    if ym > cur:
        return 0
    return today.day


def defaults(db: Session, user_id: int) -> list[Budget]:
    return (
        db.query(Budget)
        .filter(Budget.user_id == user_id, Budget.year_month.is_(None))
        .order_by(Budget.category_id.is_not(None), Budget.id)
        .all()
    )


def specials(db: Session, user_id: int) -> list[SpecialBudget]:
    return (
        db.query(SpecialBudget)
        .filter(SpecialBudget.user_id == user_id)
        .order_by(SpecialBudget.date_from.desc(), SpecialBudget.id.desc())
        .all()
    )


def category_meta(db: Session, ids: set[int], locale: str) -> dict[int, dict]:
    if not ids:
        return {}
    names = _category_names(db, list(ids), locale)
    return {
        c.id: {"name": names.get(c.id, c.key), "icon": c.icon, "color": c.color}
        for c in db.query(Category).filter(Category.id.in_(ids)).all()
    }


def special_spent(db: Session, user_id: int, sb: SpecialBudget, scope: set[int] | None) -> int:
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.user_id == user_id,
        Transaction.deleted_at.is_(None),
        Transaction.direction == Direction.expense,
        Transaction.date >= sb.date_from,
        Transaction.date <= sb.date_to,
    )
    if scope is not None:
        q = q.where(Transaction.category_id.in_(scope))
    return int(db.execute(q).scalar() or 0)


def special_state(sb: SpecialBudget, today: dt.date) -> str:
    if today < sb.date_from:
        return "upcoming"
    if today > sb.date_to:
        return "ended"
    return "active"


# --------------------------------------------------------------------------
# 对外
# --------------------------------------------------------------------------


def _line(budget: int | None, base: int | None, extra: int, fc: Forecast, n: int, d: int, threshold: int) -> dict:
    finished = d >= n
    remaining_days = n - d
    status = judge(budget, fc.spent, fc, threshold, finished)
    out = {
        "budget": budget,
        "base": base,
        "special_extra": extra,
        "spent": fc.spent,
        "projected": fc.projected,
        "low": fc.low,
        "high": fc.high,
        "pace_ratio": round(fc.pace_ratio, 3) if fc.pace_ratio is not None else None,
        "status": status,
        "threshold_pct": threshold,
        # 余下每天还能花多少；预测会超时，每天要少花多少才守得住
        "daily_allowance": (max(0, budget - fc.spent) // remaining_days)
        if budget is not None and remaining_days > 0
        else None,
        "cut_per_day": (max(0, fc.projected - budget) // remaining_days)
        if budget is not None and remaining_days > 0
        else None,
    }
    return out


def status(db: Session, user_id: int, locale: str, ym: str, today: dt.date) -> dict:
    start, end = month_bounds(ym)
    n = _days(ym)
    d = _elapsed(ym, today)

    lookback_start, _ = month_bounds(shift_month(ym, -LOOKBACK_MONTHS))
    rows = _expenses(db, user_id, lookback_start, end)
    hist = _history_months(db, user_id, ym, rows)

    budget_rows = defaults(db, user_id)
    total_row = next((b for b in budget_rows if b.category_id is None), None)
    cat_rows = [b for b in budget_rows if b.category_id is not None]

    sbs = [s for s in specials(db, user_id) if s.date_from < end and s.date_to >= start]
    cat_ids = {b.category_id for b in cat_rows} | {s.category_id for s in sbs if s.category_id}
    scopes = _scopes(db, user_id, cat_ids)
    meta = category_meta(db, cat_ids, locale)

    def fc_for(scope: set[int] | None) -> Forecast:
        return forecast(
            n,
            d,
            _daily(rows, ym, n, scope, habitual=False),
            _daily(rows, ym, n, scope, habitual=True),
            [_daily(rows, h, _days(h), scope, habitual=True) for h in hist],
        )

    alloc = {s.id: allocate(s.amount, s.date_from, s.date_to, start, end) for s in sbs}

    # ---- 总额 ----
    total_extra = sum(alloc.values())
    total_budget = total_row.amount + total_extra if total_row else None
    total_fc = fc_for(None)
    total = _line(
        total_budget,
        total_row.amount if total_row else None,
        total_extra if total_row else 0,
        total_fc,
        n,
        d,
        total_row.alert_threshold_pct if total_row else 80,
    )
    total["id"] = total_row.id if total_row else None
    total["flagged_spent"] = sum(r.amount for r in rows if r.flagged and start <= r.date < end)
    total["path"] = total_fc.path

    # ---- 类目 ----
    categories = []
    budgeted: set[int] = set()
    for b in cat_rows:
        scope = scopes[b.category_id]
        budgeted |= scope
        extra = sum(alloc[s.id] for s in sbs if s.category_id and s.category_id in scope)
        fc = fc_for(scope)
        line = _line(b.amount + extra, b.amount, extra, fc, n, d, b.alert_threshold_pct)
        line.update({"id": b.id, "category_id": b.category_id, **meta.get(b.category_id, {})})
        categories.append(line)
    severity = {"over": 0, "will_exceed": 1, "likely_exceed": 2, "at_risk": 3, "on_track": 4, "none": 5}
    categories.sort(key=lambda c: (severity[c["status"]], -c["spent"]))

    unbudgeted = sum(
        r.amount for r in rows if start <= r.date < end and r.category_id not in budgeted
    ) if cat_rows else None

    # ---- 特别预算 ----
    special_out = []
    for s in sbs:
        scope = scopes.get(s.category_id) if s.category_id else None
        special_out.append(
            {
                **special_dict(s, meta),
                "allocated": alloc[s.id],
                "spent": special_spent(db, user_id, s, scope),
                "state": special_state(s, today),
            }
        )

    # ---- 近 6 个月的达成情况（总额）----
    history = []
    if total_row:
        every = specials(db, user_id)
        for k in range(6, 0, -1):
            m = shift_month(ym, -k)
            ms, me = month_bounds(m)
            if ms < lookback_start:
                continue
            extra = sum(
                allocate(s.amount, s.date_from, s.date_to, ms, me)
                for s in every
                if s.date_from < me and s.date_to >= ms
            )
            spent = sum(r.amount for r in rows if ms <= r.date < me)
            if spent or m in hist:
                history.append({"year_month": m, "budget": total_row.amount + extra, "spent": spent})

    return {
        "year_month": ym,
        "as_of": today.isoformat(),
        "days_in_month": n,
        "elapsed_days": d,
        "basis_months": len(hist),
        "total": total,
        "categories": categories,
        "unbudgeted_spent": unbudgeted,
        "specials": special_out,
        "history": history,
    }


def special_dict(s: SpecialBudget, meta: dict[int, dict]) -> dict:
    m = meta.get(s.category_id or -1, {})
    return {
        "id": s.id,
        "name": s.name,
        "kind": s.kind.value,
        "amount": s.amount,
        "date_from": s.date_from.isoformat(),
        "date_to": s.date_to.isoformat(),
        "category_id": s.category_id,
        "category_name": m.get("name"),
        "category_icon": m.get("icon"),
        "memo": s.memo,
    }


def suggest(
    db: Session, user_id: int, locale: str, today: dt.date, steps: tuple[int, int] = (1000, 5000)
) -> dict:
    """按过去的习惯给一套起步预算：各大分類取历史月份的中位数，向上取整。

    用中位数而不是平均：一次换手机、一次搬家不该把之后每个月的预算都抬高。
    """
    ym = today.strftime("%Y-%m")
    start, _ = month_bounds(shift_month(ym, -LOOKBACK_MONTHS))
    end, _ = month_bounds(ym)
    rows = [r for r in _expenses(db, user_id, start, end) if not r.flagged]
    hist = _history_months(db, user_id, ym, rows)
    if not hist:
        return {"basis_months": 0, "total": None, "categories": []}

    parent_of = dict(
        db.execute(select(Category.id, Category.parent_id).where(Category.user_id == user_id)).all()
    )
    types = dict(db.execute(select(Category.id, Category.type).where(Category.user_id == user_id)).all())

    def top(cid: int | None) -> int | None:
        if cid is None:
            return None
        return parent_of.get(cid) or cid

    per_month: dict[str, dict[int | None, int]] = {m: defaultdict(int) for m in hist}
    for r in rows:
        m = r.date.strftime("%Y-%m")
        if m in per_month:
            per_month[m][top(r.category_id)] += r.amount

    def median(values: list[int]) -> float:
        s = sorted(values)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    def ceil_to(v: float, step: int) -> int:
        return int(math.ceil(v / step) * step)

    cats: set[int] = {c for m in per_month.values() for c in m if c is not None}
    meta = category_meta(db, cats, locale)
    suggestions = []
    for c in cats:
        if types.get(c) != CategoryType.expense:
            continue
        values = [per_month[m].get(c, 0) for m in hist]
        med = median(values)
        if med <= 0:
            continue
        suggestions.append(
            {"category_id": c, "amount": ceil_to(med, steps[0]), "months": sum(1 for v in values if v), **meta.get(c, {})}
        )
    suggestions.sort(key=lambda s: -s["amount"])
    total = median([sum(per_month[m].values()) for m in hist])
    return {"basis_months": len(hist), "total": ceil_to(total, steps[1]), "categories": suggestions}
