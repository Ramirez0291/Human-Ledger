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
from app.schemas.importing import (
    BatchActionOut,
    BatchDetail,
    BatchOut,
    BulkUpdate,
    ConfirmOut,
    CsvFilePreview,
    CsvPreviewOut,
    StagedRowOut,
    StagedRowPatchOut,
    StagedRowUpdate,
    TextImportRequest,
)
from app.services.importing import history
from app.services.importing.confirm import confirm_batch
from app.services.importing.csv_source import (
    PROFILES,
    ColumnMapping,
    decode,
    detect,
    parse_csv,
    read_rows,
)
from app.services.importing.pipeline import find_previous_import, run_pipeline, source_hash
from app.services.normalize import make_fingerprint, merchant_brand, normalize_merchant
from app.services.parsing.lines import parse_lines

router = APIRouter(prefix="/imports", tags=["imports"])


# --------------------------------------------------------------------------
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

    default_direction = "expense"
    result = parse_lines(payload.text, statement_month=anchor, default_direction=default_direction)
    source.ocr_raw_json = None

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
    batch = _owned_batch(db, user, batch_id)
    if batch.status == BatchStatus.confirmed:
        raise HTTPException(status_code=409, detail="batch_already_confirmed")
    db.delete(batch)
    db.commit()


# --------------------------------------------------------------------------
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

    if "date" in data and data["date"] is not None:
        row.date_inferred = False
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
    """Apply the chosen category to same-merchant rows the user hasn't edited."""
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
# --------------------------------------------------------------------------

MAX_CSV_BYTES = 5 * 1024 * 1024


async def _read_upload(f: UploadFile) -> bytes:
    content = await f.read()
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if not content.strip():
        raise HTTPException(status_code=400, detail="file_empty")
    return content


def _suggest_account(db: Session, user: User, profile_key: str | None, kind: str | None) -> int | None:
    if profile_key is None:
        return None
    accounts = (
        db.query(Account).filter(Account.user_id == user.id, Account.is_archived.is_(False)).all()
    )
    profile = PROFILES.get(profile_key)
    needle = profile.institution if profile else ""
    for a in accounts:
        if needle and a.institution and needle in a.institution:
            return a.id
    for a in accounts:
        if needle and needle in a.name:
            return a.id
    if kind:
        for a in accounts:
            if a.type.value == kind:
                return a.id
    return None


@router.post("/csv/preview", response_model=CsvPreviewOut)
async def csv_preview(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CsvPreviewOut:
    out: list[CsvFilePreview] = []
    first_profile: str | None = None
    first_kind: str | None = None

    for f in files:
        content = await _read_upload(f)
        text, encoding = decode(content)
        rows = read_rows(text)
        det = detect(rows, f.filename or "")
        sha = source_hash(content)
        if first_profile is None and det.profile:
            first_profile, first_kind = det.profile.key, det.profile.account_kind
        out.append(
            CsvFilePreview(
                filename=f.filename or "",
                encoding=encoding,
                profile=det.profile.key if det.profile else None,
                profile_name=det.profile.name if det.profile else None,
                account_kind=det.profile.account_kind if det.profile else None,
                header=det.header,
                sample=rows[det.data_start : det.data_start + 5],
                row_count=max(0, len(rows) - det.data_start),
                mapping=det.mapping.to_dict() if det.mapping else None,
                statement_month=det.statement_month.strftime("%Y-%m") if det.statement_month else None,
                previously_imported=find_previous_import(db, user.id, sha) is not None,
                warnings=det.notes,
            )
        )

    return CsvPreviewOut(files=out, suggested_account_id=_suggest_account(db, user, first_profile, first_kind))


@router.post("/csv", response_model=BatchDetail, status_code=status.HTTP_201_CREATED)
async def import_csv(
    files: list[UploadFile] = File(...),
    account_id: int = Form(...),
    mapping: str | None = Form(default=None),
    batch_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchDetail:
    """CSV rows are never merged within a batch: identical rows are real, separate transactions."""
    account = _owned_account(db, user, account_id)

    override: ColumnMapping | None = None
    if mapping:
        try:
            override = ColumnMapping.from_dict(json.loads(mapping))
        except (ValueError, TypeError, KeyError):
            raise HTTPException(status_code=400, detail="invalid_mapping") from None

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

    for f in files:
        content = await _read_upload(f)
        sha = source_hash(content)
        if find_previous_import(db, user.id, sha) is not None:
            previously = True

        result, det, encoding = parse_csv(content, f.filename or "", mapping_override=override)
        if det.mapping is None and override is None:
            unknown.append(f.filename or "?")
            continue

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
        kind = det.profile.account_kind if det.profile and override is None else None
        if kind and kind != account.type.value:
            # Dedup is per account, so move a recognised file to the matching account type.
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
        )
        warnings.extend(f"{f.filename}: {w}" for w in result.warnings)
        if detected_balance is None and result.detected_balance is not None:
            detected_balance = result.detected_balance
        if statement_month is None and result.statement_month:
            statement_month = result.statement_month

    if unknown and len(unknown) == len(files):
        db.rollback()
        raise HTTPException(status_code=400, detail="csv_unknown_format")
    if unknown:
        warnings.append("csv:unknown_format:" + ",".join(unknown))

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
