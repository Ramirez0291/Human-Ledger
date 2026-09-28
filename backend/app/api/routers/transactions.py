from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.enums import Direction, TxnSource
from app.db.models import Account, Category, CategoryName, Transaction, User
from app.db.session import get_db
from app.schemas.ledger import (
    CategorySuggestion,
    ConvertToTransfer,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TransferCreate,
)
from app.services.merchants import learn, suggest_category, suggest_merchants
from app.services.normalize import make_fingerprint, normalize_merchant
from app.services.reports import category_scope

router = APIRouter(prefix="/transactions", tags=["transactions"])

TRANSFER_DIRECTIONS = (Direction.transfer_in, Direction.transfer_out)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


def _owned_account(db: Session, user: User, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=404, detail="account_not_found")
    return account


def _check_category(db: Session, user: User, category_id: int | None) -> None:
    if category_id is None:
        return
    category = db.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=404, detail="category_not_found")


def _apply_derived(txn: Transaction) -> None:
    txn.merchant_norm = normalize_merchant(txn.merchant_raw)
    txn.fingerprint = make_fingerprint(
        txn.date, txn.direction.value if txn.direction else "", txn.amount, txn.merchant_norm
    )


def _decorate(db: Session, user: User, rows: list[Transaction]) -> list[TransactionOut]:
    if not rows:
        return []

    account_names = dict(
        db.execute(select(Account.id, Account.name).where(Account.user_id == user.id)).all()
    )

    cat_ids = {r.category_id for r in rows if r.category_id}
    categories: dict[int, Category] = {}
    names: dict[int, str] = {}
    if cat_ids:
        for c in db.query(Category).filter(Category.id.in_(cat_ids)).all():
            categories[c.id] = c
        for cn in (
            db.query(CategoryName)
            .filter(CategoryName.category_id.in_(cat_ids), CategoryName.locale == user.locale)
            .all()
        ):
            names[cn.category_id] = cn.name

    out: list[TransactionOut] = []
    for r in rows:
        item = TransactionOut.model_validate(r)
        item.account_name = account_names.get(r.account_id, "")
        if r.category_id and r.category_id in categories:
            c = categories[r.category_id]
            item.category_key = c.key
            item.category_name = names.get(c.id, c.key)
            item.category_icon = c.icon
            item.category_color = c.color
        out.append(item)
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


@router.get("", response_model=TransactionPage)
def list_transactions(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    direction: Direction | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionPage:
    query = db.query(Transaction).filter(Transaction.user_id == user.id)

    if include_deleted:
        query = query.filter(Transaction.deleted_at.is_not(None))
    else:
        query = query.filter(Transaction.deleted_at.is_(None))

    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if category_id:
        query = query.filter(
            Transaction.category_id.in_(category_scope(db, user.id, category_id))
        )
    if direction:
        query = query.filter(Transaction.direction == direction)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(Transaction.merchant_raw.ilike(pattern), Transaction.memo.ilike(pattern))
        )

    total = query.with_entities(func.count(Transaction.id)).scalar() or 0

    sums = dict(
        query.with_entities(Transaction.direction, func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.direction.in_([Direction.expense, Direction.income]))
        .group_by(Transaction.direction)
        .all()
    )

    rows = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return TransactionPage(
        items=_decorate(db, user, rows),
        total=int(total),
        page=page,
        page_size=page_size,
        sum_income=int(sums.get(Direction.income, 0)),
        sum_expense=int(sums.get(Direction.expense, 0)),
    )


@router.get("/merchants", response_model=list[str])
def merchant_autocomplete(
    q: str = Query(default="", max_length=128),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[str]:
    return suggest_merchants(db, user.id, q)


@router.get("/suggest-category", response_model=CategorySuggestion)
def category_suggestion(
    merchant: str = Query(default="", max_length=512),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CategorySuggestion:
    category_id, confidence = suggest_category(db, user.id, merchant)
    return CategorySuggestion(category_id=category_id, confidence=confidence)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionOut:
    _owned_account(db, user, payload.account_id)
    _check_category(db, user, payload.category_id)

    txn = Transaction(user_id=user.id, source=TxnSource.manual, **payload.model_dump())
    _apply_derived(txn)
    db.add(txn)

    learn(db, user.id, txn.merchant_raw, txn.category_id)

    db.commit()
    db.refresh(txn)
    return _decorate(db, user, [txn])[0]


@router.post("/transfer", response_model=list[TransactionOut], status_code=status.HTTP_201_CREATED)
def create_transfer(
    payload: TransferCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TransactionOut]:
    """Creates a transfer as two linked rows; neither counts as income or expense."""
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(status_code=400, detail="same_account")

    src = _owned_account(db, user, payload.from_account_id)
    dst = _owned_account(db, user, payload.to_account_id)
    _check_category(db, user, payload.fee_category_id)

    group_id = str(uuid.uuid4())
    label = f"{src.name} → {dst.name}"

    out_leg = Transaction(
        user_id=user.id,
        account_id=src.id,
        date=payload.date,
        direction=Direction.transfer_out,
        amount=payload.amount,
        merchant_raw=label,
        memo=payload.memo,
        source=TxnSource.manual,
        transfer_group_id=group_id,
    )
    in_leg = Transaction(
        user_id=user.id,
        account_id=dst.id,
        date=payload.date,
        direction=Direction.transfer_in,
        amount=payload.amount,
        merchant_raw=label,
        memo=payload.memo,
        source=TxnSource.manual,
        transfer_group_id=group_id,
    )
    for leg in (out_leg, in_leg):
        _apply_derived(leg)
        db.add(leg)

    created = [out_leg, in_leg]

    if payload.fee > 0:
        fee_txn = Transaction(
            user_id=user.id,
            account_id=src.id,
            date=payload.date,
            direction=Direction.expense,
            amount=payload.fee,
            merchant_raw=label,
            category_id=payload.fee_category_id,
            memo=payload.memo,
            source=TxnSource.manual,
            transfer_group_id=group_id,
        )
        _apply_derived(fee_txn)
        db.add(fee_txn)
        created.append(fee_txn)

    db.commit()
    for t in created:
        db.refresh(t)
    return _decorate(db, user, created)


@router.post("/{txn_id}/to-transfer", response_model=list[TransactionOut])
def convert_to_transfer(
    txn_id: int,
    payload: ConvertToTransfer,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TransactionOut]:
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.user_id != user.id or txn.deleted_at is not None:
        raise HTTPException(status_code=404, detail="transaction_not_found")
    if txn.transfer_group_id or txn.direction not in (Direction.expense, Direction.income):
        raise HTTPException(status_code=400, detail="already_transfer")
    other = _owned_account(db, user, payload.counterpart_account_id)
    if other.id == txn.account_id:
        raise HTTPException(status_code=400, detail="same_account")
    mine = db.get(Account, txn.account_id)

    outgoing = txn.direction == Direction.expense
    src, dst = (mine, other) if outgoing else (other, mine)
    group_id = str(uuid.uuid4())
    label = f"{src.name} → {dst.name}"
    original = txn.merchant_raw

    txn.direction = Direction.transfer_out if outgoing else Direction.transfer_in
    txn.merchant_raw = label
    txn.memo = original if not txn.memo else f"{original} / {txn.memo}"
    txn.category_id = None
    txn.exclude_from_analysis = False
    txn.transfer_group_id = group_id
    _apply_derived(txn)

    leg = Transaction(
        user_id=user.id,
        account_id=other.id,
        date=txn.date,
        time=txn.time,
        direction=Direction.transfer_in if outgoing else Direction.transfer_out,
        amount=txn.amount,
        merchant_raw=label,
        memo=txn.memo,
        source=txn.source,
        import_batch_id=txn.import_batch_id,
        transfer_group_id=group_id,
    )
    _apply_derived(leg)
    db.add(leg)
    db.commit()
    db.refresh(txn)
    db.refresh(leg)
    return _decorate(db, user, [txn, leg])


@router.patch("/{txn_id}", response_model=TransactionOut)
def update_transaction(
    txn_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.user_id != user.id:
        raise HTTPException(status_code=404, detail="transaction_not_found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("exclude_from_analysis", False) is None:
        data.pop("exclude_from_analysis")

    if "direction" in data and data["direction"] in TRANSFER_DIRECTIONS:
        raise HTTPException(status_code=400, detail="cannot_set_transfer_direction")
    if txn.transfer_group_id and ("amount" in data or "direction" in data):
        raise HTTPException(status_code=400, detail="edit_transfer_via_delete_recreate")

    if "account_id" in data:
        _owned_account(db, user, data["account_id"])
    if "category_id" in data:
        _check_category(db, user, data["category_id"])

    for key, value in data.items():
        setattr(txn, key, value)
    _apply_derived(txn)

    if "category_id" in data or "merchant_raw" in data:
        learn(db, user.id, txn.merchant_raw, txn.category_id)

    db.commit()
    db.refresh(txn)
    return _decorate(db, user, [txn])[0]


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Soft delete. Deleting one leg of a transfer deletes both."""
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.user_id != user.id or txn.deleted_at is not None:
        raise HTTPException(status_code=404, detail="transaction_not_found")

    now = dt.datetime.now(dt.timezone.utc)
    if txn.transfer_group_id:
        siblings = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.transfer_group_id == txn.transfer_group_id,
                Transaction.deleted_at.is_(None),
            )
            .all()
        )
        for s in siblings:
            s.deleted_at = now
    else:
        txn.deleted_at = now

    db.commit()


@router.post("/{txn_id}/restore", response_model=TransactionOut)
def restore_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.user_id != user.id or txn.deleted_at is None:
        raise HTTPException(status_code=404, detail="transaction_not_found")

    if txn.transfer_group_id:
        siblings = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.transfer_group_id == txn.transfer_group_id,
            )
            .all()
        )
        for s in siblings:
            s.deleted_at = None
    else:
        txn.deleted_at = None

    db.commit()
    db.refresh(txn)
    return _decorate(db, user, [txn])[0]
