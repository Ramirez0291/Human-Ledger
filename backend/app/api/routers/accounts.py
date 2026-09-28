"""账户管理与余额对账（需求书 F1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Account, BalanceSnapshot, Transaction, User
from app.db.session import get_db
from app.schemas.ledger import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    ReconcileOut,
    ReconcileRequest,
)
from app.services.balances import compute_balance, compute_balances, reconcile

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _get_owned(db: Session, user: User, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=404, detail="account_not_found")
    return account


def _to_out(db: Session, account: Account, balance: int, txn_count: int) -> AccountOut:
    last = db.execute(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account.id)
        .order_by(BalanceSnapshot.date.desc(), BalanceSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    out = AccountOut.model_validate(account)
    out.balance = balance
    out.transaction_count = txn_count
    if last is not None:
        out.last_reconcile_diff = last.diff
        out.last_reconcile_date = last.date
    return out


@router.get("", response_model=list[AccountOut])
def list_accounts(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AccountOut]:
    q = db.query(Account).filter(Account.user_id == user.id)
    if not include_archived:
        q = q.filter(Account.is_archived.is_(False))
    accounts = q.order_by(Account.sort_order, Account.id).all()

    balances = compute_balances(db, user.id)
    counts = {
        aid: n
        for aid, n in db.execute(
            select(Transaction.account_id, func.count(Transaction.id))
            .where(Transaction.user_id == user.id, Transaction.deleted_at.is_(None))
            .group_by(Transaction.account_id)
        ).all()
    }

    return [_to_out(db, a, balances.get(a.id, a.opening_balance), counts.get(a.id, 0)) for a in accounts]


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccountOut:
    account = Account(user_id=user.id, **payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_out(db, account, account.opening_balance, 0)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccountOut:
    account = _get_owned(db, user, account_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    db.refresh(account)

    count = (
        db.query(func.count(Transaction.id))
        .filter(Transaction.account_id == account.id, Transaction.deleted_at.is_(None))
        .scalar()
        or 0
    )
    return _to_out(db, account, compute_balance(db, account), count)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除账户。

    仍有交易的账户不允许删除——直接删会让历史账目失去归属，或因外键约束
    静默失败。此时应引导用户改为「归档」（is_archived），账目保留但不再出现
    在录入选项里。
    """
    account = _get_owned(db, user, account_id)
    count = (
        db.query(func.count(Transaction.id))
        .filter(Transaction.account_id == account.id, Transaction.deleted_at.is_(None))
        .scalar()
        or 0
    )
    if count:
        raise HTTPException(status_code=409, detail="account_has_transactions")

    db.delete(account)
    db.commit()


@router.post("/{account_id}/reconcile", response_model=ReconcileOut)
def reconcile_account(
    account_id: int,
    payload: ReconcileRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReconcileOut:
    """录入实际余额并与系统计算值比对，差额非 0 即提示可能漏记。"""
    account = _get_owned(db, user, account_id)
    snapshot = reconcile(
        db,
        account,
        date=payload.date,
        actual_balance=payload.actual_balance,
        note=payload.note,
    )
    db.commit()
    return ReconcileOut(
        date=snapshot.date,
        actual_balance=snapshot.balance,
        computed_balance=snapshot.computed_balance or 0,
        diff=snapshot.diff or 0,
    )


@router.get("/{account_id}/reconciliations", response_model=list[ReconcileOut])
def list_reconciliations(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReconcileOut]:
    account = _get_owned(db, user, account_id)
    rows = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account.id)
        .order_by(BalanceSnapshot.date.desc(), BalanceSnapshot.id.desc())
        .limit(50)
        .all()
    )
    return [
        ReconcileOut(
            date=r.date,
            actual_balance=r.balance,
            computed_balance=r.computed_balance or 0,
            diff=r.diff or 0,
        )
        for r in rows
    ]
