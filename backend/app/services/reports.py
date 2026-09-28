"""报表聚合（需求书 F6）。

所有口径都沿用 balances.py：转账两条腿不计入收支；金额为整数日元。
按月聚合的查询全部走 transactions(user_id, date) 索引，10 万条量级下单次
查询在 SQLite 上是毫秒级，所以不做缓存。

筛选条件（账户 / 类目 / 关键词）对每个板块的含义：
- 账户：只看该账户的交易
- 类目：选大分類时含其子类；选子类只看子类
- 关键词：商家名或备注包含
账户视图板块不受类目 / 关键词筛选影响——它回答的是「各账户现在有多少钱」。

「除外」是另一层，只作用于分析口径（收支合计、分类、商家、趋势、每日）：
- 交易上的 exclude_from_analysis 标记：用户把搬家、买电脑、住院这类一次性开支标出来
- max_single：临时阈值，单笔支出超过它就不算（看「日常开支」用）
- exclude_category_ids：临时把整个类目拿掉（例如先不看房租，只看可变开支）
被除外的金额不会消失，每个板块都会返回它，界面上可以一键看回原貌。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

from sqlalchemy import Select, and_, case, func, not_, or_, select
from sqlalchemy.orm import Session

from app.db.enums import Direction
from app.db.models import Account, Category, CategoryName, Transaction
from app.services.balances import SIGNED_AMOUNT, compute_balances
from app.services.categorize.dictionary import lookup_all
from app.services.importing.counterpart import suggest_counterpart

TOP_MERCHANTS = 10


@dataclass(frozen=True)
class ReportFilters:
    account_id: int | None = None
    category_id: int | None = None
    q: str | None = None
    # ---- 除外（只影响分析口径）----
    exclude_flagged: bool = True
    max_single: int | None = None
    exclude_category_ids: tuple[int, ...] = ()

    @property
    def excludes_anything(self) -> bool:
        return self.exclude_flagged or self.max_single is not None or bool(self.exclude_category_ids)

    def without_exclusions(self) -> "ReportFilters":
        return replace(self, exclude_flagged=False, max_single=None, exclude_category_ids=())


def month_bounds(ym: str) -> tuple[dt.date, dt.date]:
    """'2026-09' → (2026-09-01, 2026-10-01)，右开区间。"""
    start = dt.date.fromisoformat(f"{ym}-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start, end


def shift_month(ym: str, delta: int) -> str:
    y, m = (int(x) for x in ym.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def category_scope(db: Session, user_id: int, category_id: int) -> list[int]:
    """大分類展开为自身 + 子类；子类只含自身。"""
    ids = [category_id]
    children = db.execute(
        select(Category.id).where(Category.user_id == user_id, Category.parent_id == category_id)
    ).scalars()
    ids.extend(children)
    return ids


def _apply_filters(stmt: Select, db: Session, user_id: int, f: ReportFilters) -> Select:
    if f.account_id:
        stmt = stmt.where(Transaction.account_id == f.account_id)
    if f.category_id:
        stmt = stmt.where(Transaction.category_id.in_(category_scope(db, user_id, f.category_id)))
    if f.q:
        pattern = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(Transaction.merchant_raw.ilike(pattern), Transaction.memo.ilike(pattern))
        )
    return _apply_exclusions(stmt, db, user_id, f)


def _apply_exclusions(stmt: Select, db: Session, user_id: int, f: ReportFilters) -> Select:
    if f.exclude_flagged:
        stmt = stmt.where(Transaction.exclude_from_analysis.is_(False))
    if f.max_single is not None:
        # 阈值只针对支出：一笔大额收入（奖金）不是「意外开支」
        stmt = stmt.where(
            not_(and_(Transaction.direction == Direction.expense, Transaction.amount > f.max_single))
        )
    if f.exclude_category_ids:
        ids: set[int] = set()
        for cid in f.exclude_category_ids:
            ids.update(category_scope(db, user_id, cid))
        stmt = stmt.where(or_(Transaction.category_id.is_(None), Transaction.category_id.notin_(ids)))
    return stmt


def _totals(db: Session, user_id: int, start: dt.date, end: dt.date, f: ReportFilters) -> dict:
    stmt = (
        select(
            Transaction.direction,
            func.coalesce(func.sum(Transaction.amount), 0),
            func.count(Transaction.id),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.direction.in_([Direction.expense, Direction.income]),
        )
        .group_by(Transaction.direction)
    )
    rows = db.execute(_apply_filters(stmt, db, user_id, f)).all()
    by = {d: (int(a), int(c)) for d, a, c in rows}
    income, income_n = by.get(Direction.income, (0, 0))
    expense, expense_n = by.get(Direction.expense, (0, 0))
    return {
        "income": income,
        "expense": expense,
        "net": income - expense,
        "count": income_n + expense_n,
    }


def _category_names(db: Session, ids: list[int], locale: str) -> dict[int, str]:
    if not ids:
        return {}
    return {
        cn.category_id: cn.name
        for cn in db.query(CategoryName)
        .filter(CategoryName.category_id.in_(ids), CategoryName.locale == locale)
        .all()
    }


def category_breakdown(
    db: Session,
    user_id: int,
    locale: str,
    start: dt.date,
    end: dt.date,
    f: ReportFilters,
    direction: Direction = Direction.expense,
) -> dict:
    """按大分類汇总，每个大分類内再按子类拆分（下钻数据一次给全）。

    返回 {"total", "uncategorized", "items": [{category_id, name, icon, color,
    amount, count, share, children: [...]}]}，items 按金额降序。
    """
    stmt = (
        select(
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.amount), 0),
            func.count(Transaction.id),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.direction == direction,
            Transaction.date >= start,
            Transaction.date < end,
        )
        .group_by(Transaction.category_id)
    )
    rows = db.execute(_apply_filters(stmt, db, user_id, f)).all()
    if not rows:
        return {"total": 0, "uncategorized": 0, "items": []}

    uncategorized = 0
    leaf: dict[int, tuple[int, int]] = {}
    for cid, amount, count in rows:
        if cid is None:
            uncategorized += int(amount)
        else:
            leaf[int(cid)] = (int(amount), int(count))

    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(leaf.keys())).all()}
    parent_ids = {c.parent_id for c in cats.values() if c.parent_id}
    for p in db.query(Category).filter(Category.id.in_(parent_ids)).all():
        cats[p.id] = p
    names = _category_names(db, list(cats.keys()), locale)

    groups: dict[int, dict] = {}
    for cid, (amount, count) in leaf.items():
        c = cats.get(cid)
        if c is None:
            continue
        top = cats.get(c.parent_id) if c.parent_id else c
        if top is None:
            top = c
        g = groups.setdefault(
            top.id,
            {
                "category_id": top.id,
                "key": top.key,
                "name": names.get(top.id, top.key),
                "icon": top.icon,
                "color": top.color,
                "amount": 0,
                "count": 0,
                "children": [],
            },
        )
        g["amount"] += amount
        g["count"] += count
        g["children"].append(
            {
                "category_id": c.id,
                "key": c.key,
                "name": names.get(c.id, c.key),
                "icon": c.icon,
                "amount": amount,
                "count": count,
            }
        )

    total = sum(g["amount"] for g in groups.values()) + uncategorized
    items = sorted(groups.values(), key=lambda g: g["amount"], reverse=True)
    for g in items:
        g["share"] = round(g["amount"] / total, 4) if total else 0
        g["children"].sort(key=lambda x: x["amount"], reverse=True)
        for ch in g["children"]:
            ch["share"] = round(ch["amount"] / g["amount"], 4) if g["amount"] else 0
    return {"total": total, "uncategorized": uncategorized, "items": items}


def top_merchants(
    db: Session,
    user_id: int,
    start: dt.date,
    end: dt.date,
    f: ReportFilters,
    limit: int = TOP_MERCHANTS,
) -> list[dict]:
    """当月支出最多的商家。按规范化名聚合，显示最近一次的原始写法。"""
    stmt = (
        select(
            Transaction.merchant_norm,
            func.coalesce(func.sum(Transaction.amount), 0).label("amount"),
            func.count(Transaction.id),
            func.max(Transaction.merchant_raw),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.direction == Direction.expense,
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.merchant_norm != "",
        )
        .group_by(Transaction.merchant_norm)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(limit)
    )
    rows = db.execute(_apply_filters(stmt, db, user_id, f)).all()
    return [
        {"merchant_norm": norm, "merchant": raw, "amount": int(amount), "count": int(count)}
        for norm, amount, count, raw in rows
    ]


def account_view(db: Session, user_id: int, start: dt.date, end: dt.date) -> list[dict]:
    """各账户当前余额与当月变动（含转账，因为转账确实改变了账户余额）。"""
    balances = compute_balances(db, user_id)
    rows = db.execute(
        select(
            Transaction.account_id,
            func.coalesce(func.sum(SIGNED_AMOUNT), 0),
            func.coalesce(
                func.sum(case((Transaction.direction == Direction.income, Transaction.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Transaction.direction == Direction.expense, Transaction.amount), else_=0)),
                0,
            ),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= start,
            Transaction.date < end,
        )
        .group_by(Transaction.account_id)
    ).all()
    movement = {int(aid): (int(d), int(i), int(e)) for aid, d, i, e in rows}

    accounts = (
        db.query(Account)
        .filter(Account.user_id == user_id, Account.is_archived.is_(False))
        .order_by(Account.sort_order, Account.id)
        .all()
    )
    out = []
    for a in accounts:
        delta, income, expense = movement.get(a.id, (0, 0, 0))
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "type": a.type.value,
                "color": a.color,
                "balance": balances.get(a.id, a.opening_balance),
                "month_delta": delta,
                "month_income": income,
                "month_expense": expense,
            }
        )
    return out


def overview(db: Session, user_id: int, locale: str, ym: str, f: ReportFilters) -> dict:
    start, end = month_bounds(ym)
    prev_start, prev_end = month_bounds(shift_month(ym, -1))
    totals = _totals(db, user_id, start, end, f)
    raw = _totals(db, user_id, start, end, f.without_exclusions()) if f.excludes_anything else totals
    return {
        "year_month": ym,
        "totals": totals,
        # 除外之前的原貌，以及被拿掉的部分。界面用它显示「已除外 ¥X（N 笔）」
        "raw_totals": raw,
        "excluded": {
            "expense": raw["expense"] - totals["expense"],
            "income": raw["income"] - totals["income"],
            "count": raw["count"] - totals["count"],
        },
        "previous": _totals(db, user_id, prev_start, prev_end, f),
        "expense_by_category": category_breakdown(db, user_id, locale, start, end, f),
        "income_by_category": category_breakdown(
            db, user_id, locale, start, end, f, Direction.income
        ),
        "top_merchants": top_merchants(db, user_id, start, end, f),
        "accounts": account_view(db, user_id, start, end),
    }


def trend(db: Session, user_id: int, end_ym: str, months: int, f: ReportFilters) -> list[dict]:
    """截止 end_ym（含）往前 months 个月的收支与结余。没有交易的月份补 0。"""
    first_ym = shift_month(end_ym, -(months - 1))
    start, _ = month_bounds(first_ym)
    _, end = month_bounds(end_ym)

    # SQLite 上 date 列存为 ISO 字符串，截取前 7 位即年月；这比逐月 12 次查询快
    ym_expr = func.substr(Transaction.date, 1, 7)
    stmt = (
        select(
            ym_expr.label("ym"),
            Transaction.direction,
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.direction.in_([Direction.expense, Direction.income]),
        )
        .group_by("ym", Transaction.direction)
    )
    def collect(filters: ReportFilters) -> dict[str, dict[str, int]]:
        acc: dict[str, dict[str, int]] = {}
        for ym, direction, amount in db.execute(_apply_filters(stmt, db, user_id, filters)).all():
            acc.setdefault(ym, {"income": 0, "expense": 0})[direction.value] = int(amount)
        return acc

    kept = collect(f)
    raw = collect(f.without_exclusions()) if f.excludes_anything else kept

    zero = {"income": 0, "expense": 0}
    out = []
    ym = first_ym
    for _ in range(months):
        v = kept.get(ym, zero)
        r = raw.get(ym, zero)
        out.append(
            {
                "month": ym,
                "income": v["income"],
                "expense": v["expense"],
                "net": v["income"] - v["expense"],
                "excluded_expense": r["expense"] - v["expense"],
                "excluded_income": r["income"] - v["income"],
            }
        )
        ym = shift_month(ym, 1)
    return out


def daily(db: Session, user_id: int, ym: str, f: ReportFilters) -> dict:
    """本月与上月逐日支出。界面据此画「每日支出 + 累计」并与上月同期对比。"""

    def per_day(month: str, filters: ReportFilters) -> dict[int, int]:
        start, end = month_bounds(month)
        stmt = (
            select(Transaction.date, func.coalesce(func.sum(Transaction.amount), 0))
            .where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.direction == Direction.expense,
                Transaction.date >= start,
                Transaction.date < end,
            )
            .group_by(Transaction.date)
        )
        return {d.day: int(a) for d, a in db.execute(_apply_filters(stmt, db, user_id, filters)).all()}

    start, end = month_bounds(ym)
    prev = shift_month(ym, -1)
    prev_start, prev_end = month_bounds(prev)
    kept = per_day(ym, f)
    raw = per_day(ym, f.without_exclusions()) if f.excludes_anything else kept
    prev_kept = per_day(prev, f)
    return {
        "year_month": ym,
        "days": [
            {
                "day": d,
                "expense": kept.get(d, 0),
                "excluded": raw.get(d, 0) - kept.get(d, 0),
            }
            for d in range(1, (end - start).days + 1)
        ],
        "previous": [
            {"day": d, "expense": prev_kept.get(d, 0)} for d in range(1, (prev_end - prev_start).days + 1)
        ],
    }


def large_expenses(db: Session, user_id: int, locale: str, ym: str, f: ReportFilters, limit: int = 8) -> list[dict]:
    """本月单笔最大的支出，外加所有已标记除外的支出——给用户一处地方逐笔决定「算不算」。

    这里不套用除外条件（否则被除外的就看不到了），只套用账户 / 类目 / 关键词筛选。
    """
    start, end = month_bounds(ym)
    base = f.without_exclusions()
    cond = (
        Transaction.user_id == user_id,
        Transaction.deleted_at.is_(None),
        Transaction.direction == Direction.expense,
        Transaction.date >= start,
        Transaction.date < end,
    )
    top = db.execute(
        _apply_filters(select(Transaction).where(*cond), db, user_id, base)
        .order_by(Transaction.amount.desc(), Transaction.id)
        .limit(limit)
    ).scalars().all()
    flagged = db.execute(
        _apply_filters(
            select(Transaction).where(*cond, Transaction.exclude_from_analysis.is_(True)), db, user_id, base
        )
    ).scalars().all()

    seen: dict[int, Transaction] = {t.id: t for t in top}
    for t in flagged:
        seen.setdefault(t.id, t)
    rows = sorted(seen.values(), key=lambda t: (-t.amount, t.id))

    cat_ids = [t.category_id for t in rows if t.category_id]
    names = _category_names(db, cat_ids, locale)
    icons = {c.id: c.icon for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()} if cat_ids else {}
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    by_id = {a.id: a for a in accounts}

    def transfer_like(t: Transaction) -> bool:
        # 信用卡还款 / 取现 / 充值 / 转入证券：钱只是换了个账户，不是消费
        return any(e.transfer for e in lookup_all(t.merchant_norm or ""))

    def counterpart(t: Transaction) -> int | None:
        account = by_id.get(t.account_id)
        return suggest_counterpart(accounts, account, t.merchant_raw, "expense") if account else None

    return [
        {
            "id": t.id,
            "account_id": t.account_id,
            "account_name": by_id[t.account_id].name if t.account_id in by_id else "",
            "date": t.date.isoformat(),
            "merchant": t.merchant_raw,
            "amount": t.amount,
            "category_id": t.category_id,
            "category_name": names.get(t.category_id) if t.category_id else None,
            "category_icon": icons.get(t.category_id) if t.category_id else None,
            "exclude_from_analysis": t.exclude_from_analysis,
            # 被阈值拿掉的也要让界面知道，否则用户会困惑「我没标它怎么也不算了」
            "over_threshold": f.max_single is not None and t.amount > f.max_single,
            "transfer_like": transfer_like(t),
            "suggested_counterpart_id": counterpart(t) if transfer_like(t) else None,
        }
        for t in rows
    ]
