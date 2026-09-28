"""导入管道：RawTransaction[] → 待确认区（staged_transactions）。

与来源无关。截图（M2）、文本粘贴、CSV（后续）都在各自的来源模块里产出
RawTransaction 列表，然后交给这里：

    规范化 → 指纹 → 批内合并（L1/L2）→ 库内判重（L3/L3b）→ 分类判别链 → 落表

之后由用户在待确认区核对，confirm.py 负责真正写入 transactions。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import BatchStatus, Direction, DupStatus
from app.db.models import Account, ImportBatch, ImportImage, StagedTransaction
from app.services.categorize.engine import Categorizer
from app.services.importing.counterpart import suggest_counterpart
from app.services.importing.dedup import (
    Candidate,
    check_against_ledger,
    group_within_batch,
)
from app.services.normalize import make_fingerprint, normalize_merchant
from app.services.ocr.base import ExtractResult


@dataclass
class PipelineStats:
    total: int = 0
    staged: int = 0
    excluded: int = 0
    merged: int = 0
    duplicates: int = 0
    maybe: int = 0
    transfer_hints: int = 0
    categorized: int = 0


def run_pipeline(
    db: Session,
    *,
    user_id: int,
    account: Account,
    batch: ImportBatch,
    source: ImportImage | None,
    result: ExtractResult,
    merge_within_batch: bool = True,
) -> PipelineStats:
    """把一次识别结果写入待确认区。调用方负责 commit。"""
    stats = PipelineStats(total=len(result.transactions))
    categorizer = Categorizer(db, user_id)
    all_accounts = db.query(Account).filter(Account.user_id == user_id).all()

    rows: list[StagedTransaction] = []
    cands: list[Candidate] = []

    # ---- 1. 规范化 + 指纹 + 分类 ----
    for idx, raw in enumerate(result.transactions):
        norm = normalize_merchant(raw.merchant_raw)
        direction = raw.direction or "expense"
        fp = (
            make_fingerprint(raw.date, direction, raw.amount, norm)
            if (raw.amount is not None and raw.date is not None)
            else ""
        )

        row = StagedTransaction(
            user_id=user_id,
            batch_id=batch.id,
            source_image_id=source.id if source else None,
            account_id=account.id,
            date=raw.date,
            time=raw.time,
            direction=Direction(direction),
            amount=raw.amount,
            merchant_raw=raw.merchant_raw,
            merchant_norm=norm,
            fingerprint=fp,
            confidence=raw.confidence,
            date_inferred=raw.date_inferred,
            excluded=raw.excluded,
            exclude_reason=raw.exclude_reason or None,
            balance_after=raw.balance_after,
            raw_text=raw.raw_text or None,
            is_selected=not raw.excluded,
        )
        if raw.installment:
            row.installment_current = raw.installment.get("current_time")
            row.installment_total = raw.installment.get("total_times")
            row.installment_total_amount = raw.installment.get("total_amount")
            if raw.installment.get("estimated"):
                row.memo = "installment_estimated"

        if not raw.excluded:
            verdict = categorizer.classify(raw.merchant_raw, account.id, direction)
            row.category_id = verdict.category_id
            row.category_confidence = verdict.confidence
            row.category_source = verdict.source
            row.transfer_hint = verdict.transfer_hint
            if verdict.category_id is not None:
                stats.categorized += 1
            if verdict.transfer_hint:
                stats.transfer_hints += 1
                # 能认出对方账户就预填：电子钱包的自动充值、ATM、卡还款每月十几笔，
                # 不该让用户逐行手选。用户仍可改可清
                row.counterpart_account_id = suggest_counterpart(
                    all_accounts, account, raw.merchant_raw, direction
                )
        else:
            stats.excluded += 1

        rows.append(row)
        cands.append(
            Candidate(
                key=idx,
                fingerprint=fp,
                date=raw.date,
                direction=direction,
                amount=raw.amount,
                merchant_norm=norm,
            )
        )

    # ---- 2. 批内合并（L1/L2）----
    active = [c for c, r in zip(cands, rows) if not r.excluded]
    groups = group_within_batch(active)
    merged_keys: dict[int, int] = {}  # 被合并 key → 幸存者 key
    for survivor, dups in groups.items():
        if merge_within_batch:
            rows[survivor].merged_count = 1 + len(dups)
            rows[survivor].dup_status = DupStatus.merged
            rows[survivor].dup_reason = f"merged:{len(dups)}"
            for k in dups:
                merged_keys[k] = survivor
            stats.merged += len(dups)
        else:
            # CSV：文件内相同行多半是真实的多笔，只标黄不合并
            for k in [survivor, *dups]:
                rows[k].dup_status = DupStatus.maybe
                rows[k].dup_reason = f"same_in_batch:{1 + len(dups)}"
                stats.maybe += 1

    # 先落表拿到 id，才能填 merged_into_id
    for row in rows:
        db.add(row)
    db.flush()

    for k, survivor in merged_keys.items():
        rows[k].excluded = True
        rows[k].exclude_reason = "merged"
        rows[k].merged_into_id = rows[survivor].id
        rows[k].is_selected = False

    # ---- 3. 库内判重（L3/L3b/L3c）----
    for c, row in zip(cands, rows):
        if row.excluded:
            continue
        verdict = check_against_ledger(db, user_id, c, account_id=account.id, transfer_hint=row.transfer_hint)
        if verdict.status == DupStatus.duplicate:
            row.dup_status = DupStatus.duplicate
            row.dup_reason = verdict.reason
            row.dup_ref_id = verdict.ref_id
            row.is_selected = False  # 默认不勾选，但绝不删除
            stats.duplicates += 1
        elif verdict.status == DupStatus.maybe and row.dup_status != DupStatus.merged:
            row.dup_status = DupStatus.maybe
            row.dup_reason = verdict.reason
            row.dup_ref_id = verdict.ref_id
            # 默认勾选：同日同额同商家可能是真实的两笔
            stats.maybe += 1

    stats.staged = sum(1 for r in rows if not r.excluded)
    batch.file_count = (batch.file_count or 0) + 1
    batch.status = BatchStatus.draft
    return stats


def source_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_previous_import(db: Session, user_id: int, sha256: str) -> ImportImage | None:
    """同一份来源是否已经导入过（不论是否已确认）。"""
    return (
        db.execute(
            select(ImportImage)
            .join(ImportBatch, ImportBatch.id == ImportImage.batch_id)
            .where(
                ImportBatch.user_id == user_id,
                ImportImage.sha256 == sha256,
                ImportBatch.status != BatchStatus.reverted,  # 撤销后重导是正常操作
            )
            .order_by(ImportImage.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


