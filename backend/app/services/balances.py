from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.db.enums import Direction
from app.db.models import Account, BalanceSnapshot, Transaction

# Signed amount shared by balances and reports.
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
    q = _base_query(account.user_id).where(Transaction.account_id == account.id)
    if account.opening_date is not None:
        q = q.where(Transaction.date >= account.opening_date)
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    delta = db.scalar(q) or 0
    return account.opening_balance + int(delta)


def compute_balances(db: Session, user_id: int) -> dict[int, int]:
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
