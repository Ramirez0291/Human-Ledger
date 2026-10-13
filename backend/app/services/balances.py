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

两种记账风格（用户偏好 ledger_mode，见 services/preferences.py）
------------------------------------------------------------------
strict   就是上面的口径，逐笔累加。漏记会直接体现在余额上，靠对账差额提示。

relaxed  （默认）个人账本会漏记，余额不该被漏记拖着走：
  1. 有过对账 / 导入时读到的真实余额（balance_snapshots），就以**最近一次**为起点，
     只累加它之后的流水——用户说现金是 0，现金就是 0
  2. 信用卡按天累加时最高到 0：还款比已记的刷卡多，多出的是在还没导入的旧账单。
     否则银行明细比卡明细早几个月，余额就会是几十万的「正数」
  3. 现金 / 交通 IC / 电子钱包最低到 0：花出去的比记进来的多，是有充值或取现没记
  银行、证券不设上下限：它们的真实余额靠导入明细里的残高自动校准。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.db.enums import AccountType, Direction
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


_CEIL_ZERO = {AccountType.credit_card}
_FLOOR_ZERO = {AccountType.cash, AccountType.prepaid, AccountType.emoney}


def _clamp(kind: AccountType, value: int) -> int:
    if kind in _CEIL_ZERO:
        return min(0, value)
    if kind in _FLOOR_ZERO:
        return max(0, value)
    return value


def _relaxed_balances(db: Session, user_id: int, accounts: list[Account]) -> dict[int, int]:
    daily: dict[int, list[tuple[dt.date, int]]] = {}
    for account_id, date, net in db.execute(
        select(Transaction.account_id, Transaction.date, func.sum(SIGNED_AMOUNT))
        .where(Transaction.user_id == user_id, Transaction.deleted_at.is_(None))
        .group_by(Transaction.account_id, Transaction.date)
        .order_by(Transaction.account_id, Transaction.date)
    ).all():
        daily.setdefault(account_id, []).append((date, int(net)))

    anchors: dict[int, BalanceSnapshot] = {}
    for snap in (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.user_id == user_id)
        .order_by(BalanceSnapshot.date, BalanceSnapshot.id)
        .all()
    ):
        anchors[snap.account_id] = snap  # 按时间顺序覆盖，留下最近的一条

    result: dict[int, int] = {}
    for acc in accounts:
        anchor = anchors.get(acc.id)
        balance = anchor.balance if anchor else acc.opening_balance
        since = anchor.date if anchor else None
        balance = _clamp(acc.type, balance)
        # 按天而不是按笔夹：同一天先还款后刷卡，逐笔夹会把还款吃掉
        for date, net in daily.get(acc.id, []):
            if since is not None and date <= since:
                continue
            balance = _clamp(acc.type, balance + net)
        result[acc.id] = balance
    return result


def compute_balances(db: Session, user_id: int, mode: str | None = None) -> dict[int, int]:
    """一次算出该用户所有账户的当前余额，避免逐账户 N 次查询。

    mode 为空时按用户的记账风格（默认 relaxed）。
    """
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    if not accounts:
        return {}
    if mode is None:
        from app.services.preferences import ledger_mode

        mode = ledger_mode(db, user_id)
    if mode == "relaxed":
        return _relaxed_balances(db, user_id, accounts)

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
