"""Dedup: L1/L2 within batch, L3 exact fingerprint, L3b fuzzy, L3c transfer leg."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import Direction, DupStatus
from app.db.models import Transaction
from app.services.normalize import similarity

DEFAULT_FUZZY_THRESHOLD = 0.85
DEFAULT_DATE_TOLERANCE_DAYS = 1


@dataclass
class DupVerdict:
    status: DupStatus
    reason: str
    ref_id: int | None = None


@dataclass
class Candidate:
    key: int
    fingerprint: str
    date: dt.date | None
    direction: str
    amount: int | None
    merchant_norm: str


def _fmt(date: dt.date | None, merchant: str, amount: int | None) -> str:
    d = f"{date.month}/{date.day}" if date else "?"
    a = f"¥{amount:,}" if amount is not None else "?"
    return f"{d} {merchant or '?'} {a}"


def group_within_batch(cands: list[Candidate]) -> dict[int, list[int]]:
    by_fp: dict[str, list[int]] = {}
    for c in cands:
        if not c.fingerprint or c.amount is None or c.date is None:
            continue
        by_fp.setdefault(c.fingerprint, []).append(c.key)
    return {keys[0]: keys[1:] for keys in by_fp.values() if len(keys) > 1}


def check_against_ledger(
    db: Session,
    user_id: int,
    cand: Candidate,
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    date_tolerance: int = DEFAULT_DATE_TOLERANCE_DAYS,
    account_id: int | None = None,
    transfer_hint: bool = False,
) -> DupVerdict:
    if cand.amount is None or cand.date is None:
        return DupVerdict(DupStatus.none, "")

    if transfer_hint and account_id is not None:
        leg_dir = Direction.transfer_in if cand.direction == "income" else Direction.transfer_out
        lo = cand.date - dt.timedelta(days=date_tolerance)
        hi = cand.date + dt.timedelta(days=date_tolerance)
        leg = db.execute(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.account_id == account_id,
                Transaction.direction == leg_dir,
                Transaction.amount == cand.amount,
                Transaction.date >= lo,
                Transaction.date <= hi,
            )
            .order_by(Transaction.id)
            .limit(1)
        ).scalar_one_or_none()
        if leg is not None:
            return DupVerdict(
                DupStatus.duplicate,
                f"transfer_leg:{_fmt(leg.date, leg.merchant_raw, leg.amount)}",
                leg.id,
            )

    # Fingerprints are not unique (CSV rows are not merged); take any one.
    exact = db.execute(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.fingerprint == cand.fingerprint,
        )
        .order_by(Transaction.id)
        .limit(1)
    ).scalar_one_or_none()
    if exact is not None:
        return DupVerdict(
            DupStatus.duplicate,
            f"exact:{_fmt(exact.date, exact.merchant_raw, exact.amount)}",
            exact.id,
        )

    lo = cand.date - dt.timedelta(days=date_tolerance)
    hi = cand.date + dt.timedelta(days=date_tolerance)
    try:
        direction = Direction(cand.direction)
    except ValueError:
        direction = Direction.expense

    near = (
        db.execute(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.amount == cand.amount,
                Transaction.direction == direction,
                Transaction.date >= lo,
                Transaction.date <= hi,
            )
        )
        .scalars()
        .all()
    )
    best: Transaction | None = None
    best_score = 0.0
    for t in near:
        score = similarity(cand.merchant_norm, t.merchant_norm)
        if score > best_score:
            best, best_score = t, score
    if best is not None and best_score >= fuzzy_threshold:
        return DupVerdict(
            DupStatus.maybe,
            f"fuzzy:{best_score:.2f}:{_fmt(best.date, best.merchant_raw, best.amount)}",
            best.id,
        )

    return DupVerdict(DupStatus.none, "")
