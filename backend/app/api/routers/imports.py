"""导入与待确认区（需求书 F3.4 / F4）。

当前来源：文本粘贴（截图上的文字按行贴入）。截图 OCR 与 CSV 接入后，
只是多几个「产出 RawTransaction」的入口，之后的判重、分类、确认全部复用。
"""

from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.enums import BatchStatus, CategorySource, Direction, DupStatus, TxnSource
from app.db.models import (
    Account,
    Category,
    CategoryName,
    ImportBatch,
    ImportImage,
    StagedTransaction,
    User,
)
from app.db.session import get_db
from app.regions import region_of
from app.schemas.importing import (
    BatchActionOut,
    BatchDetail,
    BatchOut,
    BulkUpdate,
    ConfirmOut,
    CsvFilePreview,
    CsvPreviewOut,
    PaymentMethodOut,
    StagedRowOut,
    StagedRowPatchOut,
    StagedRowUpdate,
    TextImportRequest,
)
from app.services.importing import history, payment_methods
from app.services.importing.confirm import confirm_batch
from app.services.importing.csv_source import (
    PROFILES,
    ColumnMapping,
    detect,
    load_rows,
    parse_csv,
)
from app.services.importing.payment_methods import method_key
from app.services.importing.pipeline import find_previous_import, run_pipeline, source_hash
from app.services.normalize import make_fingerprint, merchant_brand, normalize_merchant
from app.services.parsing.lines import parse_lines

router = APIRouter(prefix="/imports", tags=["imports"])


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _owned_batch(db: Session, user: User, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.user_id != user.id:
        raise HTTPException(status_code=404, detail="batch_not_found")
    return batch


def _owned_account(db: Session, user: User, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=404, detail="account_not_found")
    return account


def _owned_category(db: Session, user: User, category_id: int | None) -> None:
    """改类别前确认类别属于本人：否则能把别人的类目挂到自己的行上，顺带读到别人自定义的类目名。"""
    if category_id is None:
        return
    c = db.get(Category, category_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(status_code=404, detail="category_not_found")


def _batch_out(db: Session, batch: ImportBatch) -> BatchOut:
    out = BatchOut.model_validate(batch)
    q = db.query(StagedTransaction).filter(StagedTransaction.batch_id == batch.id)
    out.total_rows = q.count()
    out.excluded_rows = q.filter(StagedTransaction.excluded.is_(True)).count()
    out.selected_rows = q.filter(
        StagedTransaction.excluded.is_(False), StagedTransaction.is_selected.is_(True)
    ).count()
    out.duplicate_rows = q.filter(StagedTransaction.dup_status == DupStatus.duplicate).count()
    out.maybe_rows = q.filter(StagedTransaction.dup_status == DupStatus.maybe).count()
    return out


def _rows_out(db: Session, user: User, rows: list[StagedTransaction]) -> list[StagedRowOut]:
    account_names = dict(
        db.execute(select(Account.id, Account.name).where(Account.user_id == user.id)).all()
    )
    cat_ids = {r.category_id for r in rows if r.category_id}
    cats: dict[int, Category] = {}
    names: dict[int, str] = {}
    if cat_ids:
        cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}
        names = {
            cn.category_id: cn.name
            for cn in db.query(CategoryName)
            .filter(CategoryName.category_id.in_(cat_ids), CategoryName.locale == user.locale)
            .all()
        }
    out = []
    for r in rows:
        item = StagedRowOut.model_validate(r)
        item.account_name = account_names.get(r.account_id or -1, "")
        # 原始文本只在被排除的行上有用（界面用它显示「跳过了什么」）；
        # 正常行带着它会让 400 行的批次响应膨胀到几百 KB
        if not r.excluded:
            item.raw_text = None
        if r.category_id and r.category_id in cats:
            c = cats[r.category_id]
            item.category_name = names.get(c.id, c.key)
            item.category_icon = c.icon
            item.category_color = c.color
        out.append(item)
    return out


def _detail(db: Session, user: User, batch: ImportBatch, **extra) -> BatchDetail:
    rows = (
        db.query(StagedTransaction)
        .filter(StagedTransaction.batch_id == batch.id)
        .order_by(StagedTransaction.id)
        .all()
    )
    return BatchDetail(batch=_batch_out(db, batch), rows=_rows_out(db, user, rows), **extra)


# --------------------------------------------------------------------------
# 批次
# --------------------------------------------------------------------------


@router.get("", response_model=list[BatchOut])
def list_batches(
    status_filter: BatchStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BatchOut]:
    q = db.query(ImportBatch).filter(ImportBatch.user_id == user.id)
    if status_filter:
        q = q.filter(ImportBatch.status == status_filter)
    batches = q.order_by(ImportBatch.id.desc()).limit(50).all()
    return _with_history(db, user, [_batch_out(db, b) for b in batches])


def _with_history(db: Session, user: User, items: list[BatchOut]) -> list[BatchOut]:
    done = [b.id for b in items if b.status != BatchStatus.draft]
    summary = history.summarize(db, user.id, done)
    for b in items:
        s = summary.get(b.id)
        if s is None:
            continue
        b.ledger_rows = s.ledger_rows
        b.date_from, b.date_to = s.date_from, s.date_to
        b.account_names = s.account_names
        b.overlap_rows = s.overlap_rows
        b.redundant_rows = s.redundant_rows
        b.overlaps = s.overlaps
    return items


def _confirmed_batch(db: Session, user: User, batch_id: int) -> ImportBatch:
    batch = _owned_batch(db, user, batch_id)
    if batch.status != BatchStatus.confirmed:
        raise HTTPException(status_code=409, detail="batch_not_confirmed")
    return batch


@router.post("/{batch_id}/revert", response_model=BatchActionOut)
def revert_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchActionOut:
    """撤销已确认的批次：入账的交易进回收站，批次标为已撤销（可重新导入同一文件）。"""
    batch = _confirmed_batch(db, user, batch_id)
    n = history.revert(db, user.id, batch)
    db.commit()
    return BatchActionOut(removed=n, batch=_with_history(db, user, [_batch_out(db, batch)])[0])


@router.post("/{batch_id}/remove-overlaps", response_model=BatchActionOut)
def remove_batch_overlaps(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchActionOut:
    """只把这批里与其他记录重叠的交易移进回收站，另一份保留。"""
    batch = _confirmed_batch(db, user, batch_id)
    n = history.remove_overlaps(db, user.id, batch)
    db.commit()
    return BatchActionOut(removed=n, batch=_with_history(db, user, [_batch_out(db, batch)])[0])


@router.post("/text", response_model=BatchDetail, status_code=status.HTTP_201_CREATED)
def import_text(
    payload: TextImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchDetail:
    """把截图上的文字按行粘贴导入。多张截图可分多次贴入同一批次，批内自动合并重叠部分。"""
    account = _owned_account(db, user, payload.account_id)

    if payload.batch_id is not None:
        batch = _owned_batch(db, user, payload.batch_id)
        if batch.status != BatchStatus.draft:
            raise HTTPException(status_code=409, detail="batch_not_draft")
    else:
        batch = ImportBatch(user_id=user.id, source_type=TxnSource.screenshot, status=BatchStatus.draft)
        db.add(batch)
        db.flush()

    content = payload.text.encode("utf-8")
    sha = source_hash(content)
    previously = find_previous_import(db, user.id, sha)

    source = ImportImage(batch_id=batch.id, file_path=None, sha256=sha, ocr_provider="text")
    db.add(source)
    db.flush()

    anchor = None
    if payload.statement_month:
        anchor = dt.date.fromisoformat(f"{payload.statement_month}-01")

    # 账户类型决定无法判定方向时的默认值：银行流水两个方向都常见，信用卡几乎全是支出
    default_direction = "expense"
    result = parse_lines(
        payload.text,
        statement_month=anchor,
        default_direction=default_direction,
        minor_unit=region_of(user).minor_unit,
    )
    source.ocr_raw_json = None

    # 追加到已有批次时，要把之前的行也纳入批内合并：简单起见，把本次结果
    # 与已有行合在一起重新判重开销太大；这里只对新行做批内合并，
    # 与已有行的重叠交由 L3 之前的「批内既有指纹」检查处理
    existing_fps = {
        fp
        for (fp,) in db.execute(
            select(StagedTransaction.fingerprint).where(
                StagedTransaction.batch_id == batch.id,
                StagedTransaction.excluded.is_(False),
                StagedTransaction.fingerprint != "",
            )
        ).all()
    }
    if existing_fps:
        for raw in result.transactions:
            if raw.excluded or raw.amount is None or raw.date is None:
                continue
            fp = make_fingerprint(
                raw.date, raw.direction or "expense", raw.amount, normalize_merchant(raw.merchant_raw)
            )
            if fp in existing_fps:
                raw.excluded = True
                raw.exclude_reason = "merged"

    stats = run_pipeline(
        db,
        user_id=user.id,
        account=account,
        batch=batch,
        source=source,
        result=result,
        merge_within_batch=True,
    )
    db.commit()

    return _detail(
        db,
        user,
        batch,
        warnings=result.warnings + ([f"stats:merged={stats.merged}"] if stats.merged else []),
        detected_balance=result.detected_balance,
        statement_month=result.statement_month,
        previously_imported=previously is not None,
    )


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchDetail:
    return _detail(db, user, _owned_batch(db, user, batch_id))


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def discard_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """丢弃草稿批次。已确认的批次不可删（账目已入账，删了会失去来源追溯）。"""
    batch = _owned_batch(db, user, batch_id)
    if batch.status == BatchStatus.confirmed:
        raise HTTPException(status_code=409, detail="batch_already_confirmed")
    db.delete(batch)
    db.commit()


# --------------------------------------------------------------------------
# 行
# --------------------------------------------------------------------------


def _owned_row(db: Session, user: User, batch: ImportBatch, row_id: int) -> StagedTransaction:
    row = db.get(StagedTransaction, row_id)
    if row is None or row.batch_id != batch.id or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="row_not_found")
    return row


def _recompute(row: StagedTransaction) -> None:
    row.merchant_norm = normalize_merchant(row.merchant_raw)
    if row.date and row.amount is not None and row.direction:
        row.fingerprint = make_fingerprint(row.date, row.direction.value, row.amount, row.merchant_norm)


@router.patch("/{batch_id}/rows/{row_id}", response_model=StagedRowPatchOut)
def update_row(
    batch_id: int,
    row_id: int,
    payload: StagedRowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StagedRowPatchOut:
    batch = _owned_batch(db, user, batch_id)
    if batch.status != BatchStatus.draft:
        raise HTTPException(status_code=409, detail="batch_not_draft")
    row = _owned_row(db, user, batch, row_id)

    data = payload.model_dump(exclude_unset=True)
    if "account_id" in data and data["account_id"] is not None:
        _owned_account(db, user, data["account_id"])
    if "counterpart_account_id" in data and data["counterpart_account_id"] is not None:
        _owned_account(db, user, data["counterpart_account_id"])
    _owned_category(db, user, data.get("category_id"))

    for key in ("account_id", "date", "direction", "amount", "merchant_raw", "memo", "is_selected"):
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    if "category_id" in data and data["category_id"] is not None:
        row.category_id = data["category_id"]
        row.category_confidence = 1.0
    if payload.clear_category:
        row.category_id = None
    if "counterpart_account_id" in data and data["counterpart_account_id"] is not None:
        row.counterpart_account_id = data["counterpart_account_id"]
    if payload.clear_counterpart:
        row.counterpart_account_id = None

    # 用户手动填了日期 / 金额，视为不再是「推断」
    if "date" in data and data["date"] is not None:
        row.date_inferred = False
    # 被排除的行经用户编辑后视为恢复
    if row.excluded and row.exclude_reason in ("no_amount", "no_merchant", "orphan_amount") and row.amount and row.merchant_raw:
        row.excluded = False
        row.exclude_reason = None
        row.is_selected = True

    _recompute(row)

    affected: list[StagedTransaction] = []
    if payload.apply_to_similar:
        if "category_id" in data and data["category_id"] is not None:
            affected = _propagate_category(db, batch, row)
        elif ("counterpart_account_id" in data and data["counterpart_account_id"] is not None) or payload.clear_counterpart:
            affected = _propagate_counterpart(db, batch, row)

    db.commit()
    db.refresh(row)
    out = _rows_out(db, user, [row, *affected])
    return StagedRowPatchOut(row=out[0], affected=out[1:])


def _propagate_counterpart(
    db: Session, batch: ImportBatch, row: StagedTransaction
) -> list[StagedTransaction]:
    """对方账户推给同批次里同商家的疑似转账行（含「不是转账」的清空）。

    同一个商家串（「チャージ 三井住友銀行 *****40」「カード ｾﾌﾞﾝBK0UJD」）对方几乎总是同一个，
    所以不像类别那样区分用户改过没有——直接同步。
    """
    siblings = (
        db.query(StagedTransaction)
        .filter(
            StagedTransaction.batch_id == batch.id,
            StagedTransaction.id != row.id,
            StagedTransaction.excluded.is_(False),
            StagedTransaction.direction == row.direction,
            StagedTransaction.transfer_hint.is_(True),
            StagedTransaction.merchant_norm == row.merchant_norm,
        )
        .all()
    )
    changed = []
    for s in siblings:
        if s.counterpart_account_id == row.counterpart_account_id:
            continue
        s.counterpart_account_id = row.counterpart_account_id
        changed.append(s)
    return changed


def _propagate_category(
    db: Session, batch: ImportBatch, row: StagedTransaction
) -> list[StagedTransaction]:
    """把用户刚给的类别推给同批次里的同商家 / 同品牌行。

    只改「还没被用户亲手改过」的行（置信度 < 1.0），用户已经定的不动。
    连带改的行置信度记 0.9、来源记 memory，界面上能看出是推的而不是用户点的。
    """
    key_norm = row.merchant_norm
    key_brand = merchant_brand(row.merchant_raw)
    siblings = (
        db.query(StagedTransaction)
        .filter(
            StagedTransaction.batch_id == batch.id,
            StagedTransaction.id != row.id,
            StagedTransaction.excluded.is_(False),
            StagedTransaction.direction == row.direction,
        )
        .all()
    )
    changed = []
    for s in siblings:
        if (s.category_confidence or 0) >= 1.0:
            continue
        same = s.merchant_norm == key_norm or (
            bool(key_brand) and merchant_brand(s.merchant_raw) == key_brand
        )
        if not same or s.category_id == row.category_id:
            continue
        s.category_id = row.category_id
        s.category_confidence = 0.9
        s.category_source = CategorySource.memory
        changed.append(s)
    return changed


@router.post("/{batch_id}/rows/{row_id}/expand", response_model=list[StagedRowOut])
def expand_merged(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StagedRowOut]:
    """展开批内合并：把被合并进这一行的记录还原为独立行（需求书 F4.3，合并可逆）。"""
    batch = _owned_batch(db, user, batch_id)
    if batch.status != BatchStatus.draft:
        raise HTTPException(status_code=409, detail="batch_not_draft")
    survivor = _owned_row(db, user, batch, row_id)

    siblings = (
        db.query(StagedTransaction)
        .filter(StagedTransaction.batch_id == batch.id, StagedTransaction.merged_into_id == survivor.id)
        .all()
    )
    for s in siblings:
        s.excluded = False
        s.exclude_reason = None
        s.merged_into_id = None
        s.is_selected = True
        s.dup_status = DupStatus.maybe
        s.dup_reason = "expanded"
    survivor.merged_count = 1
    survivor.dup_status = DupStatus.maybe
    survivor.dup_reason = "expanded"
    db.commit()
    return _rows_out(db, user, [survivor, *siblings])


@router.post("/{batch_id}/rows/{row_id}/restore", response_model=StagedRowOut)
def restore_excluded(
    batch_id: int,
    row_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StagedRowOut:
    """把被排除的行（如汇总行、支付失败）拉回来。用户比规则更清楚。"""
    batch = _owned_batch(db, user, batch_id)
    row = _owned_row(db, user, batch, row_id)
    row.excluded = False
    row.exclude_reason = None
    row.merged_into_id = None
    row.is_selected = True
    _recompute(row)
    db.commit()
    db.refresh(row)
    return _rows_out(db, user, [row])[0]


@router.post("/{batch_id}/bulk", response_model=list[StagedRowOut])
def bulk_update(
    batch_id: int,
    payload: BulkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StagedRowOut]:
    batch = _owned_batch(db, user, batch_id)
    if batch.status != BatchStatus.draft:
        raise HTTPException(status_code=409, detail="batch_not_draft")
    if payload.account_id is not None:
        _owned_account(db, user, payload.account_id)
    _owned_category(db, user, payload.category_id)

    rows = (
        db.query(StagedTransaction)
        .filter(StagedTransaction.batch_id == batch.id, StagedTransaction.id.in_(payload.row_ids))
        .all()
    )
    for r in rows:
        if payload.category_id is not None:
            r.category_id = payload.category_id
            r.category_confidence = 1.0
        if payload.account_id is not None:
            r.account_id = payload.account_id
        if payload.is_selected is not None and not r.excluded:
            r.is_selected = payload.is_selected
    db.commit()
    return _rows_out(db, user, rows)


@router.post("/{batch_id}/confirm", response_model=ConfirmOut)
def confirm(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfirmOut:
    batch = _owned_batch(db, user, batch_id)
    if batch.status != BatchStatus.draft:
        raise HTTPException(status_code=409, detail="batch_not_draft")
    result = confirm_batch(db, user.id, batch, source=batch.source_type)
    db.commit()
    return ConfirmOut(
        imported=result.imported,
        transfers=result.transfers,
        skipped_unselected=result.skipped_unselected,
        skipped_excluded=result.skipped_excluded,
        skipped_incomplete=result.skipped_incomplete,
        skipped_duplicate=result.skipped_duplicate,
        reconcile=result.reconcile,
        warnings=result.warnings,
    )


@router.get("/{batch_id}/stats")
def batch_stats(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    batch = _owned_batch(db, user, batch_id)
    rows = db.query(StagedTransaction).filter(StagedTransaction.batch_id == batch.id)
    selected = rows.filter(StagedTransaction.excluded.is_(False), StagedTransaction.is_selected.is_(True))

    def total(q) -> int:
        return int(q.with_entities(func.coalesce(func.sum(StagedTransaction.amount), 0)).scalar() or 0)

    # 疑似转账（ATM / 还款 / 充值）确认后不计入收支，合计里单列，免得支出被虚高
    transfer = selected.filter(StagedTransaction.transfer_hint.is_(True))
    plain = selected.filter(StagedTransaction.transfer_hint.is_(False))
    return {
        "total": rows.count(),
        "selected": selected.count(),
        "expense": total(plain.filter(StagedTransaction.direction == Direction.expense)),
        "income": total(plain.filter(StagedTransaction.direction == Direction.income)),
        "transfer": total(transfer),
        "transfer_count": transfer.count(),
    }


# --------------------------------------------------------------------------
# CSV 来源
# --------------------------------------------------------------------------

MAX_CSV_BYTES = 5 * 1024 * 1024


async def _read_upload(f: UploadFile) -> bytes:
    content = await f.read()
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if not content.strip():
        raise HTTPException(status_code=400, detail="file_empty")
    return content


def _compact(text: str) -> str:
    """比较账户名与卡名用：NFKC、小写、去掉空白与分隔符。「Ｏｌｉｖｅ／クレジット」≈「Olive クレジット」"""
    import unicodedata

    t = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in t if ch.isalnum())


def _history_account(db: Session, user: User, profile_key: str, kind: str | None) -> int | None:
    """以前同一种格式的文件最后放进了哪个账户（按已确认的行数投票）。用户选过一次，下次就记住。"""
    row = db.execute(
        select(StagedTransaction.account_id, func.count())
        .join(ImportImage, ImportImage.id == StagedTransaction.source_image_id)
        .join(ImportBatch, ImportBatch.id == StagedTransaction.batch_id)
        .join(Account, Account.id == StagedTransaction.account_id)
        .where(
            ImportBatch.user_id == user.id,
            ImportBatch.status == BatchStatus.confirmed,
            ImportImage.detected_institution == profile_key,
            StagedTransaction.excluded.is_(False),
            Account.is_archived.is_(False),
            # 以前放错过（银行明细放进了信用卡）不该被当成习惯记住
            *([Account.type == kind] if kind else []),
        )
        .group_by(StagedTransaction.account_id)
        .order_by(func.count().desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def _suggest_account(
    db: Session, user: User, profile_key: str | None, kind: str | None, hints: list[str] | None = None
) -> int | None:
    """给一个识别出格式的文件推荐账户。依次看：

    1. 以前同格式的文件放进了哪个账户（学习用户的选择）
    2. 文件里写的卡名（三井住友 CSV 首行「Ｏｌｉｖｅ／クレジット」）与账户名相符
    3. 账户的机构名 / 账户名里含格式对应的机构名
    4. 同类型的第一个账户
    """
    if profile_key is None:
        return None
    remembered = _history_account(db, user, profile_key, kind)
    if remembered is not None:
        return remembered
    accounts = (
        db.query(Account).filter(Account.user_id == user.id, Account.is_archived.is_(False)).all()
    )
    same_kind = [a for a in accounts if not kind or a.type.value == kind]
    for hint in hints or []:
        label = _compact(hint.split(":", 1)[-1])
        for a in same_kind:
            name = _compact(a.name)
            if label and name and (name in label or label in name):
                return a.id
    profile = PROFILES.get(profile_key)
    needle = profile.institution if profile else ""
    for a in same_kind:
        if needle and a.institution and needle in a.institution:
            return a.id
    for a in same_kind:
        if needle and needle in a.name:
            return a.id
    return same_kind[0].id if same_kind and kind else None


def _method_labels(result) -> dict[str, tuple[str, int]]:
    """跨账户账单里出现的支付方式：键 → (最完整的原文, 涉及行数)。"""
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    for t in result.transactions:
        if t.excluded:
            continue
        for hint in (t.account_hint, t.counterpart_hint):
            if not hint:
                continue
            k = method_key(hint)
            counts[k] = counts.get(k, 0) + 1
            if len(hint) > len(labels.get(k, "")):
                labels[k] = hint
    return {k: (labels[k], counts[k]) for k in labels}


def _merge_labels(into: dict[str, tuple[str, int]], more: dict[str, tuple[str, int]]) -> None:
    for k, (label, n) in more.items():
        old_label, old_n = into.get(k, ("", 0))
        into[k] = (label if len(label) > len(old_label) else old_label, old_n + n)


@router.post("/csv/preview", response_model=CsvPreviewOut)
async def csv_preview(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CsvPreviewOut:
    """识别编码与格式，返回表头、样例行与建议映射；不落库。

    跨账户的账单（微信）另外汇总出现过的支付方式，各自给出能对上的账户或建议新建的账户。
    """
    region = region_of(user)
    out: list[CsvFilePreview] = []
    first_profile: str | None = None
    first_kind: str | None = None
    methods: dict[str, tuple[str, int]] = {}

    for f in files:
        content = await _read_upload(f)
        rows, encoding = load_rows(content)
        det = detect(rows, f.filename or "")
        sha = source_hash(content)
        profile = det.profile
        mismatch = profile is not None and profile.currency != region.currency
        multi = profile is not None and profile.multi_account
        if first_profile is None and profile and not multi and not mismatch:
            first_profile, first_kind = profile.key, profile.account_kind
        suggested = (
            _suggest_account(db, user, profile.key, profile.account_kind, det.notes)
            if profile and not multi
            else None
        )
        if multi and not mismatch:
            result, _, _ = parse_csv(content, f.filename or "")
            _merge_labels(methods, _method_labels(result))
        out.append(
            CsvFilePreview(
                filename=f.filename or "",
                encoding=encoding,
                profile=profile.key if profile else None,
                profile_name=profile.name if profile else None,
                account_kind=profile.account_kind if profile else None,
                header=det.header,
                sample=rows[det.data_start : det.data_start + 5],
                row_count=max(0, len(rows) - det.data_start),
                mapping=det.mapping.to_dict() if det.mapping else None,
                statement_month=det.statement_month.strftime("%Y-%m") if det.statement_month else None,
                previously_imported=find_previous_import(db, user.id, sha) is not None,
                warnings=det.notes,
                suggested_account_id=suggested,
                multi_account=multi,
                currency=profile.currency if profile else region.currency,
                currency_mismatch=mismatch,
            )
        )

    resolved = payment_methods.resolve(db, user.id, list(methods))
    pm_out = []
    for key, (label, count) in methods.items():
        new = payment_methods.new_account_for(label)
        pm_out.append(
            PaymentMethodOut(
                key=key,
                label=label,
                count=count,
                account_id=resolved.get(key),
                new_name=new.name,
                new_type=new.type.value,
                new_institution=new.institution,
            )
        )
    # 平台钱包（零钱 / 支付宝余额）在前，其余按笔数
    pm_out.sort(key=lambda m: (m.key not in payment_methods.HOMES, -m.count))

    return CsvPreviewOut(
        files=out,
        suggested_account_id=_suggest_account(db, user, first_profile, first_kind),
        payment_methods=pm_out,
    )


class _MethodAccounts:
    """一次导入里「支付方式键 → 账户」的解析。用户选了「新建」或从没映射过的，按原文建账户；
    同一次导入里的多份文件共用，避免同一张卡建出两个账户。"""

    def __init__(self, db: Session, user: User, chosen: dict[str, int | str]) -> None:
        self.db, self.user, self.chosen = db, user, chosen
        self.cache: dict[str, int] = {}
        self.created: list[str] = []

    def account_for(self, key: str, label: str) -> int:
        if key in self.cache:
            return self.cache[key]
        choice = self.chosen.get(key)
        account_id: int | None = None
        if isinstance(choice, int) and choice > 0:
            account_id = _owned_account(self.db, self.user, choice).id
        elif choice is None:
            account_id = payment_methods.resolve(self.db, self.user.id, [key]).get(key)
        if account_id is None:
            new = payment_methods.new_account_for(label)
            account = Account(
                user_id=self.user.id,
                name=new.name[:128],
                type=new.type,
                institution=new.institution,
                opening_balance=0,
            )
            self.db.add(account)
            self.db.flush()
            account_id = account.id
            self.created.append(new.name)
        self.cache[key] = account_id
        return account_id


@router.post("/csv", response_model=BatchDetail, status_code=status.HTTP_201_CREATED)
async def import_csv(
    files: list[UploadFile] = File(...),
    account_id: int | None = Form(default=None),
    account_ids: list[int] | None = Form(default=None),
    mapping: str | None = Form(default=None),
    payment_accounts: str | None = Form(default=None),
    batch_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchDetail:
    """导入一个或多个 CSV / xlsx 到同一批次。

    与截图不同，CSV 由银行生成，文件内的相同行几乎都是真实的多笔交易，
    因此批内**不合并**，只标黄提示（merge_within_batch=False）。

    账户：`account_ids` 与 files 一一对应（每个文件各选各的，一批里可以同时有银行、
    几张信用卡和 PayPay）；只给 `account_id` 时整批共用一个。逐个选过的尊重用户，
    类型对不上只提示；整批共用时认得出格式就改放到对应类型的账户。

    跨账户的账单（微信）不看文件账户（对应项可传 0），按 `payment_accounts`
    （JSON：支付方式键 → 账户 id 或 "new"）逐行落账户；没给的按上次的选择或名字猜，
    都对不上就新建。确认过的映射记下来，下次预览直接带出。

    文件币种与账本币种（地区包）不符的整份跳过：同一个整数在日元与人民币下是两种金额。
    """
    region = region_of(user)

    def owned_or_none(i: int) -> Account | None:
        return None if i <= 0 else _owned_account(db, user, i)

    if account_ids:
        if len(account_ids) != len(files):
            raise HTTPException(status_code=400, detail="account_ids_mismatch")
        per_file = [owned_or_none(i) for i in account_ids]
    elif account_id is not None:
        per_file = [owned_or_none(account_id)] * len(files)
    else:
        per_file = [None] * len(files)
    explicit = bool(account_ids)

    override: ColumnMapping | None = None
    if mapping:
        try:
            override = ColumnMapping.from_dict(json.loads(mapping))
        except (ValueError, TypeError, KeyError):
            raise HTTPException(status_code=400, detail="invalid_mapping") from None

    chosen: dict[str, int | str] = {}
    if payment_accounts:
        try:
            raw = json.loads(payment_accounts)
            if not isinstance(raw, dict):
                raise ValueError
            chosen = {method_key(str(k)): v for k, v in raw.items() if isinstance(v, (int, str))}
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_payment_accounts") from None
    methods = _MethodAccounts(db, user, chosen)

    if batch_id is not None:
        batch = _owned_batch(db, user, batch_id)
        if batch.status != BatchStatus.draft:
            raise HTTPException(status_code=409, detail="batch_not_draft")
    else:
        batch = ImportBatch(user_id=user.id, source_type=TxnSource.csv, status=BatchStatus.draft)
        db.add(batch)
        db.flush()

    warnings: list[str] = []
    previously = False
    detected_balance: int | None = None
    statement_month: str | None = None
    unknown: list[str] = []
    skipped = 0
    used_methods: dict[str, int] = {}

    for f, account in zip(files, per_file):
        content = await _read_upload(f)
        sha = source_hash(content)
        if find_previous_import(db, user.id, sha) is not None:
            previously = True

        # 手动映射只给认不出格式的文件用：一批里混着三井住友与未知银行时，
        # 不能拿未知银行的列映射去读三井住友
        result, det, encoding = parse_csv(content, f.filename or "", minor_unit=region.minor_unit)
        if det.profile is None and override is not None:
            result, det, encoding = parse_csv(
                content, f.filename or "", mapping_override=override, minor_unit=region.minor_unit
            )
        if det.profile is None and det.mapping is None and override is None:
            unknown.append(f.filename or "?")
            continue
        if det.profile is not None and det.profile.currency != region.currency:
            warnings.append(f"currency_mismatch|{f.filename}|{det.profile.currency}|{region.currency}")
            skipped += 1
            continue

        account_map: dict[str, int] | None = None
        if det.profile is not None and det.profile.multi_account:
            account_map = {
                key: methods.account_for(key, label) for key, (label, _) in _method_labels(result).items()
            }
            used_methods.update(account_map)
            # 文件账户只用来挂没有支付方式的行（都是被排除的行）：优先平台钱包，没用到就随便取一个
            # 已映射的账户——账单里没出现零钱，就不该为它凭空建一个「微信零钱」
            home = det.profile.home or ""
            fallback = account_map.get(home) or next(iter(account_map.values()), None)
            if fallback is None:
                fallback = account.id if account is not None else methods.account_for(home, home)
            account = db.get(Account, fallback)
        elif account is None:
            db.rollback()
            raise HTTPException(status_code=422, detail="account_required")

        source = ImportImage(
            batch_id=batch.id,
            file_path=None,
            sha256=sha,
            ocr_provider=f"csv:{encoding}",
            detected_institution=det.profile.key if det.profile else None,
        )
        db.add(source)
        db.flush()

        target = account
        kind = det.profile.account_kind if det.profile and account_map is None else None
        if kind and kind != account.type.value and explicit:
            warnings.append(f"account_mismatch|{f.filename}|{det.profile.name}|{account.name}")
        elif kind and kind != account.type.value:
            # 银行口座明細选成了信用卡账户（或反过来）：判重按账户比对，放错账户后
            # 每一行都「不重复」，还款也变成了消费。认得出格式就放进对的账户
            alt_id = _suggest_account(db, user, det.profile.key, kind)
            alt = db.get(Account, alt_id) if alt_id else None
            if alt is not None and alt.type.value == kind:
                target = alt
                warnings.append(f"rerouted|{f.filename}|{det.profile.name}|{alt.name}")
            else:
                warnings.append(f"account_mismatch|{f.filename}|{det.profile.name}|{account.name}")

        run_pipeline(
            db,
            user_id=user.id,
            account=target,
            batch=batch,
            source=source,
            result=result,
            merge_within_batch=False,
            account_map=account_map,
        )
        warnings.extend(f"{f.filename}: {w}" for w in result.warnings)
        if detected_balance is None and result.detected_balance is not None:
            detected_balance = result.detected_balance
        if statement_month is None and result.statement_month:
            statement_month = result.statement_month

    if (unknown or skipped) and len(unknown) + skipped == len(files):
        db.rollback()
        raise HTTPException(
            status_code=400, detail="csv_unknown_format" if unknown else "csv_currency_mismatch"
        )
    if unknown:
        warnings.append("csv:unknown_format:" + ",".join(unknown))
    if methods.created:
        warnings.append("accounts_created|" + "、".join(methods.created))
    if used_methods:
        payment_methods.remember(db, user.id, used_methods)

    batch.note = ", ".join(f.filename or "" for f in files)[:255]
    db.commit()

    return _detail(
        db,
        user,
        batch,
        warnings=warnings,
        detected_balance=detected_balance,
        statement_month=statement_month,
        previously_imported=previously,
    )
