"""三层判重（需求书 F4.2 / F4.3）。

    L1/L2  批内重复    同一批次内指纹相同（截图滚动重叠）→ 合并为一条，可展开还原
    L3     库内重复    与已入账交易指纹相同                → 标「重复」，默认不勾选
    L3b    模糊匹配    金额相同 ∧ 日期差 ≤ 1 天 ∧ 商家相似度 ≥ 阈值 → 标「可能重复」，默认勾选但高亮
    L3c    转账另一侧  疑似转账的行，本账户已有同额、同向、日期相近的转账腿 → 标「重复」

L3c 解决的是跨账户重复：银行明细里的「ﾍﾟｲﾍﾟｲ 20,000」确认为转账后，PayPay 端
再导入「チャージ 20,000」——商家名完全不同（指纹对不上、相似度为 0），
但它就是同一笔钱的另一侧记录。

铁律（F4.3）：**L3 / L3b 一律不自动删除**。同日同额同商家的两笔交易在现实中
确实存在（Olive 样本里 09/01 与 09/02 各一笔 230 円 ミニストップ），最终决定权在用户。

批内合并是否开启由来源决定：截图的滚动重叠是常态，应合并；CSV 由银行生成，
文件内的相同行几乎都是真实的多笔交易，不应合并（只标黄）。
"""

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
    reason: str  # 人类可读的说明，如「与 09/05 的 ローソン ¥580 重复」
    ref_id: int | None = None  # 命中的已入账交易


@dataclass
class Candidate:
    """判重所需的最小字段。"""

    key: int  # 批内序号
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
    """批内按指纹分组，返回 {幸存者 key: [被合并的 key, ...]}。

    幸存者取组内第一个（截图自上而下的第一次出现）。
    """
    by_fp: dict[str, list[int]] = {}
    for c in cands:
        if not c.fingerprint or c.amount is None or c.date is None:
            continue  # 信息不全的行不参与批内合并
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
    """L3 / L3b / L3c：与已入账交易比对。"""
    if cand.amount is None or cand.date is None:
        return DupVerdict(DupStatus.none, "")

    # L3c：疑似转账，且本账户已经有对应方向的转账腿
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

    # L3：指纹完全相同。库里同指纹可能不止一条（CSV 批内不合并，同日同额同店
    # 的两笔真实交易会各自入账），取最早的一条作为引用即可，绝不能假设唯一。
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

    # L3b：金额相同、日期相近、商家相似
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
