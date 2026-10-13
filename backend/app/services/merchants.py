"""商家自动补全与分类记忆（需求书 F2 / F5.3）。

M1 只实现判别链的第 2 层「商家记忆」——手动录入时按商家名预填类别，
并在用户改动后回写。第 1 层（用户规则）、第 3 层（内置词典）、
第 4 层（LLM 兜底）在 M2 随截图导入一并实现。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import MerchantMemory, Transaction
from app.services.normalize import merchant_brand, normalize_merchant


def suggest_merchants(db: Session, user_id: int, query: str, limit: int = 8) -> list[str]:
    """商家名自动补全：按历史使用频次排序，返回原文形式。

    同时匹配原文与规范化形式。只匹配原文的话，用户用半角输入
    「ミニストップ 日本橋3丁目」就找不到库里全角存储的
    「ミニストップ　日本橋３丁目交差点東店」——而分类预测走的是规范化路径、
    能正确命中，两者行为不一致会很费解。
    """
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
    """按商家名预测类别，返回 (category_id, 置信度)。

    置信度随命中次数递增并封顶 0.95——保留一点余量，表示这终究是推测，
    UI 上应始终允许用户改。
    """
    norm = normalize_merchant(merchant_raw)
    if not norm:
        return None, 0.0

    memory = _lookup(db, user_id, norm)
    if memory is None:
        # 精确键没记过：退回品牌键（「一蘭 - 一蘭 新宿店」→「一蘭」）
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
    """记住「这家店属于这一类」。用户每次录入或改分类时调用。

    同一商家改到新类别时覆盖旧值并重置计数——用户的最新意图优先于历史频次，
    否则改了一次分类却因为旧类别命中次数高而被顶回去，会很违和。
    """
    if category_id is None:
        return
    norm = normalize_merchant(merchant_raw)
    if not norm:
        return

    _learn_key(db, user_id, norm, category_id)
    # 同时记品牌键，让同品牌的其他分店也能预填
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
        # 会话关闭了 autoflush；同一批次里同一商家出现多次时，下一次查询必须能看到这条，
        # 否则会再插一条并撞上 (user_id, merchant_norm) 唯一约束
        db.flush()
    elif memory.category_id == category_id:
        memory.hit_count += 1
        memory.last_seen_at = now
    else:
        memory.category_id = category_id
        memory.hit_count = 1
        memory.last_seen_at = now
