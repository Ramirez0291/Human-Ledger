"""合规模式（ledger_mode = strict）的「账面紧张度」。

账面越对不上，界面越紧张。紧张度只看两件事：

1. **差额**：每个账户最近一次对账时填的实际余额，与**按现在的流水**重算到那一天的余额之差。
   用现在的流水重算而不是用对账当时存下的 diff——用户补记了漏掉的交易，差额就缩小，
   气氛随之缓和。这是合规模式的正反馈：补账 → 平静
2. **审计空白**：有交易却从没对过账、或超过 60 天没对账的账户

差额相对「月均支出」的比例决定等级（0 平静 … 4 失控），有审计空白再加一级。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import local_today
from app.db.models import Account, BalanceSnapshot, Transaction, User
from app.regions import region_of
from app.services.balances import compute_balance, monthly_summary
from app.services.reports import shift_month

STALE_DAYS = 60
# 差额 / 月均支出 的分级阈值：< 2% 小出入，< 10% 可疑，< 30% 严重，以上失控
THRESHOLDS = (0.02, 0.10, 0.30)
# 月均支出的保底值按地区包取（日本 5 万円）：刚开始记账、月支出很小时，别让一点差额就拉满警报


def _monthly_base(db: Session, user_id: int, today: dt.date, floor: int) -> int:
    ym = today.strftime("%Y-%m")
    spent = [monthly_summary(db, user_id, shift_month(ym, -k))["expense"] for k in (1, 2, 3)]
    active = [s for s in spent if s > 0]
    return max(floor, round(sum(active) / len(active)) if active else 0)


def tension(db: Session, user_id: int) -> dict:
    region = region_of(db.get(User, user_id))
    today = local_today(region.timezone)
    accounts = (
        db.query(Account).filter(Account.user_id == user_id, Account.is_archived.is_(False)).order_by(Account.id).all()
    )
    txn_counts = dict(
        db.execute(
            select(Transaction.account_id, func.count())
            .where(Transaction.user_id == user_id, Transaction.deleted_at.is_(None))
            .group_by(Transaction.account_id)
        ).all()
    )

    latest: dict[int, BalanceSnapshot] = {}
    for snap in (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.user_id == user_id)
        .order_by(BalanceSnapshot.date, BalanceSnapshot.id)
        .all()
    ):
        latest[snap.account_id] = snap

    rows = []
    total = 0
    gaps = 0
    for a in accounts:
        snap = latest.get(a.id)
        if snap is None:
            if txn_counts.get(a.id):
                gaps += 1
                rows.append({"account_id": a.id, "name": a.name, "status": "unaudited", "diff": 0, "date": None, "days": None})
            continue
        diff = snap.balance - compute_balance(db, a, as_of=snap.date)
        days = (today - snap.date).days
        stale = days > STALE_DAYS
        gaps += 1 if stale else 0
        total += abs(diff)
        rows.append(
            {
                "account_id": a.id,
                "name": a.name,
                "status": "diff" if diff else ("stale" if stale else "ok"),
                "diff": diff,
                "date": snap.date.isoformat(),
                "days": days,
            }
        )

    base = _monthly_base(db, user_id, today, region.compliance_floor)
    ratio = total / base
    level = 0 if total == 0 else 1 + sum(1 for t in THRESHOLDS if ratio >= t)
    if gaps:
        level = min(4, level + 1)

    order = {"diff": 0, "unaudited": 1, "stale": 2, "ok": 3}
    rows.sort(key=lambda r: (order[r["status"]], -abs(r["diff"])))
    return {
        "level": level,
        "total_abs_diff": total,
        "monthly_base": base,
        "ratio": round(ratio, 4),
        "gaps": gaps,
        "accounts": rows,
    }
