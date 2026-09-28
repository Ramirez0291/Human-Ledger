"""账户余额计算与对账（需求书 F1 / D5）。

余额口径：`余额 = 期初余额 + Σ(该账户所有未删除交易的带符号金额)`

带符号金额的定义是全系统的基准，报表也复用它：

    expense      → −amount
    income       → +amount
    transfer_out → −amount
    transfer_in  → +amount

信用卡账户在此口径下余额为负数（表示未偿还金额）：刷卡 10,000 円后余额
−10,000，从银行还款时生成一对转账（银行 transfer_out / 信用卡 transfer_in），
余额回到 0。这样信用卡还款既不会被计成一笔支出，也能正确反映欠款。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.db.enums import Direction
from app.db.models import Account, BalanceSnapshot, Transaction

# 带符号金额表达式。收支统计与余额计算共用，避免两处口径漂移。
SIGNED_AMOUNT = case(
    (Transaction.direction == Direction.income, Transaction.amount),
    (Transaction.direction == Direction.transfer_in, Transaction.amount),
    else_=-Transaction.amount,
).cast(Integer)


def _base_query(user_id: int):
    return select(func.coalesce(func.sum(SIGNED_AMOUNT), 0)).where(
        Transaction.user_id == user_id,
        Transaction.deleted_at.is_(None),
    )


def compute_balance(db: Session, account: Account, as_of: dt.date | None = None) -> int:
    """算出账户在某日期（含）结束时的余额。as_of 为 None 表示至今。"""
    q = _base_query(account.user_id).where(Transaction.account_id == account.id)
    if account.opening_date is not None:
        q = q.where(Transaction.date >= account.opening_date)
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    delta = db.scalar(q) or 0
    return account.opening_balance + int(delta)


def compute_balances(db: Session, user_id: int) -> dict[int, int]:
    """一次算出该用户所有账户的当前余额，避免逐账户 N 次查询。"""
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    if not accounts:
        return {}

    rows = db.execute(
        select(Transaction.account_id, func.coalesce(func.sum(SIGNED_AMOUNT), 0))
        .where(Transaction.user_id == user_id, Transaction.deleted_at.is_(None))
        .group_by(Transaction.account_id)
    ).all()
    deltas = {account_id: int(total) for account_id, total in rows}

    result: dict[int, int] = {}
    for acc in accounts:
        # 期初日之前的交易本应不存在；若存在（用户补录历史），此处一并计入，
        # 因为把它们排除掉会让余额对不上，反而更难排查。
        result[acc.id] = acc.opening_balance + deltas.get(acc.id, 0)
    return result


def reconcile(
    db: Session,
    account: Account,
    date: dt.date,
    actual_balance: int,
    source: str = "manual",
    note: str | None = None,
) -> BalanceSnapshot:
    """录入某日的实际余额并与系统计算值比对。

    差额不为 0 即说明该日期之前有交易未记录（或多记了）。这是需求书 F1 中
    防漏记的核心手段——用户不必逐笔核对，只要余额对得上就说明没漏。
    """
    computed = compute_balance(db, account, as_of=date)
    snapshot = BalanceSnapshot(
        user_id=account.user_id,
        account_id=account.id,
        date=date,
        balance=actual_balance,
        computed_balance=computed,
        diff=actual_balance - computed,
        source=source,
        note=note,
    )
    db.add(snapshot)
    return snapshot


def monthly_summary(db: Session, user_id: int, year_month: str) -> dict[str, int]:
    """某月的收入 / 支出 / 结余。

    转账两条腿均排除在外——否则从银行取现会被记成一笔支出，
    信用卡还款也会与刷卡消费重复计入。
    """
    start = dt.date.fromisoformat(f"{year_month}-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

    rows = db.execute(
        select(Transaction.direction, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.direction.in_([Direction.expense, Direction.income]),
        )
        .group_by(Transaction.direction)
    ).all()

    totals = {d: int(v) for d, v in rows}
    income = totals.get(Direction.income, 0)
    expense = totals.get(Direction.expense, 0)
    return {"income": income, "expense": expense, "net": income - expense}
