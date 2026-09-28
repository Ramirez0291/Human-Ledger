from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.enums import BatchStatus, Direction
from app.db.models import Account, ImportBatch, Transaction

TRANSFER = (Direction.transfer_in, Direction.transfer_out)


@dataclass
class LedgerSummary:
    ledger_rows: int = 0
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    account_names: list[str] = field(default_factory=list)
    overlap_rows: int = 0
    redundant_rows: int = 0
    overlaps: dict[int, int] = field(default_factory=dict)


def _overlap_pairs(db: Session, user_id: int, batch_ids: list[int]) -> list[tuple[int, int, int, bool]]:
    t = aliased(Transaction)
    u = aliased(Transaction)
    is_transfer = or_(u.direction.in_(TRANSFER), t.direction.in_(TRANSFER))
    earlier = case(
        (u.import_batch_id.is_not(None), u.import_batch_id < t.import_batch_id),
        else_=u.created_at < ImportBatch.created_at,
    )
    q = (
        select(t.import_batch_id, t.id, func.coalesce(u.import_batch_id, 0), earlier)
        .join(ImportBatch, ImportBatch.id == t.import_batch_id)
        .join(
            u,
            and_(
                u.user_id == t.user_id,
                u.id != t.id,
                u.date == t.date,
                u.amount == t.amount,
                u.deleted_at.is_(None),
                or_(u.import_batch_id.is_(None), u.import_batch_id != t.import_batch_id),
                or_(
                    u.merchant_norm == t.merchant_norm,
                    and_(u.account_id == t.account_id, is_transfer),
                    and_(u.direction.in_(TRANSFER), u.memo == t.merchant_raw),
                    and_(t.direction.in_(TRANSFER), t.memo == u.merchant_raw),
                ),
            ),
        )
        .where(t.user_id == user_id, t.deleted_at.is_(None), t.import_batch_id.in_(batch_ids))
    )
    return [(b, tid, other, bool(e)) for b, tid, other, e in db.execute(q).all()]


def _group_siblings(db: Session, user_id: int, ids: set[int]) -> dict[int, set[int]]:
    if not ids:
        return {}
    legs = db.execute(
        select(Transaction.id, Transaction.transfer_group_id).where(
            Transaction.id.in_(ids), Transaction.transfer_group_id.is_not(None)
        )
    ).all()
    groups = {g for _, g in legs}
    if not groups:
        return {}
    members: dict[str, set[int]] = defaultdict(set)
    for tid, g, bid in db.execute(
        select(Transaction.id, Transaction.transfer_group_id, Transaction.import_batch_id).where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.transfer_group_id.in_(groups),
        )
    ).all():
        members[g].add(tid)
    return {tid: members[g] for tid, g in legs}


def summarize(db: Session, user_id: int, batch_ids: list[int]) -> dict[int, LedgerSummary]:
    out = {bid: LedgerSummary() for bid in batch_ids}
    if not batch_ids:
        return out

    names = dict(db.execute(select(Account.id, Account.name).where(Account.user_id == user_id)).all())
    rows = db.execute(
        select(
            Transaction.import_batch_id,
            Transaction.account_id,
            func.count(),
            func.min(Transaction.date),
            func.max(Transaction.date),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.import_batch_id.in_(batch_ids),
        )
        .group_by(Transaction.import_batch_id, Transaction.account_id)
    ).all()
    for bid, account_id, n, lo, hi in rows:
        s = out[bid]
        s.ledger_rows += n
        s.date_from = lo if s.date_from is None else min(s.date_from, lo)
        s.date_to = hi if s.date_to is None else max(s.date_to, hi)
        s.account_names.append(names.get(account_id, "?"))

    seen: dict[int, set[int]] = defaultdict(set)
    per_other: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    redundant: dict[int, set[int]] = defaultdict(set)
    pairs = _overlap_pairs(db, user_id, batch_ids)
    siblings = _group_siblings(db, user_id, {p[1] for p in pairs})
    for bid, txn_id, other, is_earlier in pairs:
        for tid in siblings.get(txn_id, {txn_id}):
            seen[bid].add(tid)
            per_other[bid][other].add(tid)
            if is_earlier:
                redundant[bid].add(tid)
    for bid, ids in seen.items():
        out[bid].overlap_rows = len(ids)
        out[bid].redundant_rows = len(redundant[bid])
        out[bid].overlaps = {k: len(v) for k, v in sorted(per_other[bid].items())}
    return out


def _with_transfer_siblings(db: Session, user_id: int, txns: list[Transaction]) -> list[Transaction]:
    """Both legs of a transfer must be deleted together."""
    groups = {t.transfer_group_id for t in txns if t.transfer_group_id}
    if not groups:
        return txns
    extra = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.transfer_group_id.in_(groups),
            Transaction.deleted_at.is_(None),
        )
        .all()
    )
    by_id = {t.id: t for t in [*txns, *extra]}
    return list(by_id.values())


def _soft_delete(txns: list[Transaction]) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    for t in txns:
        t.deleted_at = now
    return len(txns)


def revert(db: Session, user_id: int, batch: ImportBatch) -> int:
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.import_batch_id == batch.id,
            Transaction.deleted_at.is_(None),
        )
        .all()
    )
    n = _soft_delete(_with_transfer_siblings(db, user_id, txns))
    batch.status = BatchStatus.reverted
    return n


def remove_overlaps(db: Session, user_id: int, batch: ImportBatch) -> int:
    ids = {txn_id for _, txn_id, _, is_earlier in _overlap_pairs(db, user_id, [batch.id]) if is_earlier}
    if not ids:
        return 0
    txns = db.query(Transaction).filter(Transaction.id.in_(ids)).all()
    return _soft_delete(_with_transfer_siblings(db, user_id, txns))
