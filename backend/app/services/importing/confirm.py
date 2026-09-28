"""确认入账：待确认区 → transactions。

只写入「已勾选且未排除」的行。每行：
  - 普通收支          → 一条 Transaction
  - 指定了对方账户    → 一对转账（transfer_out / transfer_in），不计入收支
  - 有类别            → 回写商家记忆（F5.3）
  - 有 balance_after  → 最新一行的残高自动生成对账快照，闭环「导入 → 对账」

判重在暂存时已经做过，但两个草稿同时开着时彼此看不见：同一份明细放进两个批次，
先确认的那个入账后，后确认的那个照样再写一遍。所以确认时再查一次——只拦
暂存时没查出重复、现在却有了的行；暂存时就标了重复、用户仍然勾选的行是用户的决定，不动。
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.enums import BatchStatus, Direction, DupStatus, SnapshotSource, TxnSource
from app.db.models import Account, ImportBatch, StagedTransaction, Transaction
from app.services.balances import reconcile
from app.services.merchants import learn
from app.services.normalize import make_fingerprint, normalize_merchant


@dataclass
class ConfirmResult:
    imported: int = 0
    transfers: int = 0
    skipped_unselected: int = 0
    skipped_excluded: int = 0
    skipped_incomplete: int = 0
    skipped_duplicate: int = 0
    reconcile: dict | None = None
    warnings: list[str] = field(default_factory=list)


def _new_txn(row: StagedTransaction, **overrides) -> Transaction:
    txn = Transaction(
        user_id=row.user_id,
        account_id=row.account_id,
        date=row.date,
        time=row.time,
        direction=row.direction,
        amount=row.amount,
        merchant_raw=row.merchant_raw,
        memo=row.memo if row.memo != "installment_estimated" else None,
        source=TxnSource.screenshot,
        import_batch_id=row.batch_id,
        source_image_id=row.source_image_id,
        installment_current=row.installment_current,
        installment_total=row.installment_total,
        installment_total_amount=row.installment_total_amount,
    )
    for k, v in overrides.items():
        setattr(txn, k, v)
    txn.merchant_norm = normalize_merchant(txn.merchant_raw)
    txn.fingerprint = make_fingerprint(txn.date, txn.direction.value, txn.amount, txn.merchant_norm)
    return txn


def _booked(db: Session, batch: ImportBatch, *conds) -> bool:
    """账本里（别的批次或手动记账）是否已经有满足条件的记录。"""
    q = (
        select(Transaction.id)
        .where(
            Transaction.user_id == batch.user_id,
            Transaction.deleted_at.is_(None),
            or_(Transaction.import_batch_id.is_(None), Transaction.import_batch_id != batch.id),
            *conds,
        )
        .limit(1)
    )
    return db.execute(q).first() is not None


def _is_late_duplicate(db: Session, batch: ImportBatch, row: StagedTransaction, fingerprint: str) -> bool:
    """暂存时没查出重复、现在账本里却有了——是暂存之后才入账的。

    暂存时已判为重复 / 可能重复、用户仍然勾选的行是用户的决定，不在这里拦。
    （不按时间戳比：Windows 时钟粒度约 15ms，前后脚的两次操作会落在同一刻。）
    """
    if row.dup_status != DupStatus.none:
        return False
    if _booked(db, batch, Transaction.account_id == row.account_id, Transaction.fingerprint == fingerprint):
        return True
    if row.counterpart_account_id or row.transfer_hint:
        # 转账的另一侧（L3c）：同账户、同额、同向的转账腿，日期差 ≤ 1 天
        leg = Direction.transfer_out if row.direction == Direction.expense else Direction.transfer_in
        return _booked(
            db,
            batch,
            Transaction.account_id == row.account_id,
            Transaction.direction == leg,
            Transaction.amount == row.amount,
            Transaction.date.between(row.date - dt.timedelta(days=1), row.date + dt.timedelta(days=1)),
        )
    return False


def confirm_batch(db: Session, user_id: int, batch: ImportBatch, source: TxnSource) -> ConfirmResult:
    """把批次内勾选的行写入账本。调用方负责 commit。"""
    result = ConfirmResult()

    rows = (
        db.execute(
            select(StagedTransaction)
            .where(StagedTransaction.batch_id == batch.id, StagedTransaction.user_id == user_id)
            .order_by(StagedTransaction.id)
        )
        .scalars()
        .all()
    )

    accounts = {a.id: a for a in db.query(Account).filter(Account.user_id == user_id).all()}
    latest_balance: tuple[StagedTransaction, int] | None = None

    for row in rows:
        if row.excluded:
            result.skipped_excluded += 1
            continue
        if not row.is_selected:
            result.skipped_unselected += 1
            continue
        if row.date is None or row.amount is None or row.account_id is None:
            result.skipped_incomplete += 1
            continue

        account = accounts.get(row.account_id)
        if account is None:
            result.skipped_incomplete += 1
            continue

        counterpart = accounts.get(row.counterpart_account_id) if row.counterpart_account_id else None

        fingerprint = make_fingerprint(row.date, row.direction.value, row.amount, normalize_merchant(row.merchant_raw))
        if _is_late_duplicate(db, batch, row, fingerprint):
            result.skipped_duplicate += 1
            continue

        if counterpart is not None and counterpart.id != account.id:
            # 转账：钱离开本账户（expense）→ 本账户 out、对方 in；反之亦然
            group = str(uuid.uuid4())
            outgoing = row.direction == Direction.expense
            src, dst = (account, counterpart) if outgoing else (counterpart, account)
            label = f"{src.name} → {dst.name}"
            leg_out = _new_txn(
                row,
                source=source,
                account_id=src.id,
                direction=Direction.transfer_out,
                merchant_raw=label,
                memo=row.merchant_raw,
                category_id=None,
                transfer_group_id=group,
            )
            leg_in = _new_txn(
                row,
                source=source,
                account_id=dst.id,
                direction=Direction.transfer_in,
                merchant_raw=label,
                memo=row.merchant_raw,
                category_id=None,
                transfer_group_id=group,
            )
            db.add(leg_out)
            db.add(leg_in)
            result.transfers += 1
        else:
            txn = _new_txn(row, source=source, category_id=row.category_id)
            db.add(txn)
            if row.category_id is not None:
                learn(db, user_id, row.merchant_raw, row.category_id)
            result.imported += 1

        # 记下日期最新的一条残高，供对账
        if row.balance_after is not None:
            if latest_balance is None or (row.date, row.id) > (latest_balance[0].date, latest_balance[0].id):
                latest_balance = (row, row.balance_after)

    db.flush()

    # ---- 残高自动对账（附录 A.3.6）----
    if latest_balance is not None:
        row, balance = latest_balance
        account = accounts[row.account_id]
        snap = reconcile(
            db,
            account,
            date=row.date,
            actual_balance=balance,
            source=SnapshotSource.ocr,
            note="import:balance_after",
        )
        db.flush()
        result.reconcile = {
            "account_id": account.id,
            "account_name": account.name,
            "date": row.date.isoformat(),
            "actual_balance": snap.balance,
            "computed_balance": snap.computed_balance,
            "diff": snap.diff,
        }

    batch.status = BatchStatus.confirmed
    return result
