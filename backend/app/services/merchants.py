from __future__ import annotations

import datetime as dt

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import MerchantMemory, Transaction
from app.services.normalize import merchant_brand, normalize_merchant


def suggest_merchants(db: Session, user_id: int, query: str, limit: int = 8) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []

    conditions = [Transaction.merchant_raw.ilike(f"%{q}%")]
    q_norm = normalize_merchant(q)
    if q_norm:
        conditions.append(Transaction.merchant_norm.ilike(f"%{q_norm}%"))

    rows = db.execute(
        select(Transaction.merchant_raw, func.count(Transaction.id).label("n"))
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.merchant_raw != "",
            or_(*conditions),
        )
        .group_by(Transaction.merchant_raw)
        .order_by(desc("n"))
        .limit(limit)
    ).all()
    return [r[0] for r in rows]


def suggest_category(db: Session, user_id: int, merchant_raw: str) -> tuple[int | None, float]:
    norm = normalize_merchant(merchant_raw)
    if not norm:
        return None, 0.0

    memory = _lookup(db, user_id, norm)
    if memory is None:
        brand = merchant_brand(merchant_raw)
        if brand and brand != norm:
            memory = _lookup(db, user_id, brand)
    if memory is None:
        return None, 0.0

    confidence = min(0.95, 0.6 + 0.05 * memory.hit_count)
    return memory.category_id, confidence


def _lookup(db: Session, user_id: int, key: str) -> MerchantMemory | None:
    return db.execute(
        select(MerchantMemory).where(
            MerchantMemory.user_id == user_id,
            MerchantMemory.merchant_norm == key,
        )
    ).scalar_one_or_none()


def learn(db: Session, user_id: int, merchant_raw: str, category_id: int | None) -> None:
    if category_id is None:
        return
    norm = normalize_merchant(merchant_raw)
    if not norm:
        return

    _learn_key(db, user_id, norm, category_id)
    brand = merchant_brand(merchant_raw)
    if brand and brand != norm:
        _learn_key(db, user_id, brand, category_id)


def _learn_key(db: Session, user_id: int, norm: str, category_id: int) -> None:
    memory = _lookup(db, user_id, norm)
    now = dt.datetime.now(dt.timezone.utc)
    if memory is None:
        db.add(
            MerchantMemory(
                user_id=user_id,
                merchant_norm=norm,
                category_id=category_id,
                hit_count=1,
                last_seen_at=now,
            )
        )
        db.flush()
    elif memory.category_id == category_id:
        memory.hit_count += 1
        memory.last_seen_at = now
    else:
        memory.category_id = category_id
        memory.hit_count = 1
        memory.last_seen_at = now
