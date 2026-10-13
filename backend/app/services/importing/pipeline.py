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

from app.db.enums import BatchStatus, CategorySource, Direction, DupStatus
from app.db.models import Account, ImportBatch, ImportImage, StagedTransaction
from app.services.categorize.engine import Categorizer
from app.services.importing.counterpart import suggest_counterpart
from app.services.importing.dedup import (
    Candidate,
    check_against_ledger,
    group_within_batch,
)
from app.services.importing.payment_methods import method_key
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
    account_map: dict[str, int] | None = None,
) -> PipelineStats:
    """把一次识别结果写入待确认区。调用方负责 commit。

    account_map：跨账户来源（微信）的「支付方式键 → 账户 id」。行带 account_hint 时按它落账户，
    映射里没有的落到 `account`（文件所选账户）。
    """
    stats = PipelineStats(total=len(result.transactions))
    categorizer = Categorizer(db, user_id)
    minor_unit = categorizer.minor_unit
    all_accounts = db.query(Account).filter(Account.user_id == user_id).all()
    by_id = {a.id: a for a in all_accounts}

    def mapped(hint: str | None) -> int | None:
        if hint is None or not account_map:
            return None
        return account_map.get(method_key(hint))

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
        row_account = by_id.get(mapped(raw.account_hint) or account.id, account)

        row = StagedTransaction(
            user_id=user_id,
            batch_id=batch.id,
            source_image_id=source.id if source else None,
            account_id=row_account.id,
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
            memo=raw.memo,
            is_selected=not raw.excluded,
        )
        if raw.installment:
            row.installment_current = raw.installment.get("current_time")
            row.installment_total = raw.installment.get("total_times")
            row.installment_total_amount = raw.installment.get("total_amount")
            if raw.installment.get("estimated"):
                row.memo = "installment_estimated"

        if not raw.excluded and raw.transfer is True:
            # 来源已经知道是转账（微信的中性交易）：不分类，对方账户优先用来源给的
            row.transfer_hint = True
            stats.transfer_hints += 1
            row.counterpart_account_id = mapped(raw.counterpart_hint) or suggest_counterpart(
                all_accounts, row_account, raw.merchant_raw, direction
            )
        elif not raw.excluded:
            verdict = categorizer.classify(raw.merchant_raw, row_account.id, direction)
            if raw.category_hint and verdict.source not in (CategorySource.rule, CategorySource.memory):
                # 来源给的类目（微信红包 → 人情往来、支付宝的交易分类）比词典可靠，但让位于用户自己教过的；
                # 来源只给了大类、词典给出同一大类下的子类时（餐饮美食 vs 瑞幸 → 奶茶咖啡）用更细的
                hinted = categorizer.category_for_key(raw.category_hint, direction)
                if hinted is not None and not categorizer.refines(verdict.category_id, hinted):
                    verdict.category_id, verdict.confidence, verdict.source = hinted, 0.8, CategorySource.dictionary
            if verdict.category_id is None and raw.category_fallback:
                fallback = categorizer.category_for_key(raw.category_fallback, direction)
                if fallback is not None:
                    verdict.category_id, verdict.confidence, verdict.source = fallback, 0.6, CategorySource.dictionary
            if raw.transfer is False:
                # 来源明确说了是收支（微信「支出」/「收入」）：词典的转账提示不作数。
                # 否则「提现服务费」会因为含「提现」被当成转账
                verdict.transfer_hint = False
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
                row.counterpart_account_id = mapped(raw.counterpart_hint) or suggest_counterpart(
                    all_accounts, row_account, raw.merchant_raw, direction
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
                time=raw.time,
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
        verdict = check_against_ledger(
            db, user_id, c, account_id=row.account_id, transfer_hint=row.transfer_hint, minor_unit=minor_unit
        )
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


