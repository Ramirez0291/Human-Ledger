from __future__ import annotations

import csv
import datetime as dt
import io
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.enums import Direction
from app.db.models import Account, Category, CategoryName, Transaction, User
from app.db.session import get_db
from app.services import reports
from app.services.reports import ReportFilters

router = APIRouter(tags=["reports"])

_YM = r"^\d{4}-\d{2}$"


def _current_ym() -> str:
    today = dt.date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _filters(
    account_id: int | None = None,
    category_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=128),
    include_flagged: bool = Query(default=False, description="Include transactions flagged as excluded"),
    max_single: int | None = Query(default=None, ge=0, description="Exclude single expenses above this amount"),
    exclude_categories: str | None = Query(
        default=None, max_length=512, pattern=r"^\d+(,\d+)*$", description="Comma-separated category ids"
    ),
) -> ReportFilters:
    ids = tuple(int(x) for x in exclude_categories.split(",")) if exclude_categories else ()
    return ReportFilters(
        account_id=account_id,
        category_id=category_id,
        q=q,
        exclude_flagged=not include_flagged,
        max_single=max_single,
        exclude_category_ids=ids,
    )


@router.get("/reports/overview")
def report_overview(
    year_month: str | None = Query(default=None, pattern=_YM),
    f: ReportFilters = Depends(_filters),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return reports.overview(db, user.id, user.locale, year_month or _current_ym(), f)


@router.get("/reports/trend")
def report_trend(
    end: str | None = Query(default=None, pattern=_YM),
    months: int = Query(default=12, ge=2, le=36),
    f: ReportFilters = Depends(_filters),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return {"months": reports.trend(db, user.id, end or _current_ym(), months, f)}


@router.get("/reports/daily")
def report_daily(
    year_month: str | None = Query(default=None, pattern=_YM),
    f: ReportFilters = Depends(_filters),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return reports.daily(db, user.id, year_month or _current_ym(), f)


@router.get("/reports/large-expenses")
def report_large_expenses(
    year_month: str | None = Query(default=None, pattern=_YM),
    limit: int = Query(default=8, ge=1, le=50),
    f: ReportFilters = Depends(_filters),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return {
        "items": reports.large_expenses(db, user.id, user.locale, year_month or _current_ym(), f, limit)
    }


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

_EXPORT_COLUMNS = [
    "id",
    "date",
    "time",
    "direction",
    "amount",
    "signed_amount",
    "account",
    "category",
    "subcategory",
    "merchant",
    "merchant_norm",
    "memo",
    "source",
    "transfer_group_id",
    "installment",
    "exclude_from_analysis",
]


@router.get("/transactions/export.csv")
def export_transactions(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    direction: Direction | None = None,
    q: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    query = db.query(Transaction).filter(
        Transaction.user_id == user.id, Transaction.deleted_at.is_(None)
    )
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if category_id:
        query = query.filter(
            Transaction.category_id.in_(reports.category_scope(db, user.id, category_id))
        )
    if direction:
        query = query.filter(Transaction.direction == direction)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(Transaction.merchant_raw.ilike(pattern), Transaction.memo.ilike(pattern))
        )

    account_names = {
        a.id: a.name for a in db.query(Account).filter(Account.user_id == user.id).all()
    }
    cats = {c.id: c for c in db.query(Category).filter(Category.user_id == user.id).all()}
    names = {
        cn.category_id: cn.name
        for cn in db.query(CategoryName)
        .filter(CategoryName.category_id.in_(cats.keys()), CategoryName.locale == user.locale)
        .all()
    }

    def cat_pair(cid: int | None) -> tuple[str, str]:
        c = cats.get(cid) if cid else None
        if c is None:
            return "", ""
        if c.parent_id and c.parent_id in cats:
            return names.get(c.parent_id, cats[c.parent_id].key), names.get(c.id, c.key)
        return names.get(c.id, c.key), ""

    def rows():
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        yield "﻿"  # BOM so Excel reads UTF-8
        w.writerow(_EXPORT_COLUMNS)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
        for t in query.order_by(Transaction.date, Transaction.id).yield_per(500):
            top, sub = cat_pair(t.category_id)
            sign = 1 if t.direction in (Direction.income, Direction.transfer_in) else -1
            installment = (
                f"{t.installment_current}/{t.installment_total}"
                if t.installment_total and t.installment_total > 1
                else ""
            )
            w.writerow(
                [
                    t.id,
                    t.date.isoformat(),
                    t.time.strftime("%H:%M") if t.time else "",
                    t.direction.value,
                    t.amount,
                    sign * t.amount,
                    account_names.get(t.account_id, ""),
                    top,
                    sub,
                    t.merchant_raw,
                    t.merchant_norm,
                    t.memo or "",
                    t.source.value,
                    t.transfer_group_id or "",
                    installment,
                    1 if t.exclude_from_analysis else 0,
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    stamp = dt.date.today().strftime("%Y%m%d")
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ledger-{stamp}.csv"'},
    )


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


@router.get("/backup")
def download_backup(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),  # noqa: ARG001
) -> FileResponse:
    """Uses the SQLite online backup API; copying the file directly would miss data still in the WAL."""
    if not settings.resolved_database_url.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="backup_sqlite_only")
    db_path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="human-ledger-backup-"))
    snapshot = tmp_dir / "ledger.db"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = tmp_dir / f"human-ledger-backup-{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snapshot, "ledger.db")
        uploads = settings.uploads_dir
        for p in sorted(uploads.rglob("*")):
            if p.is_file():
                zf.write(p, Path("uploads") / p.relative_to(uploads))
        zf.writestr(
            "MANIFEST.txt",
            f"Human Ledger backup\ncreated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
            "restore: python scripts/restore_backup.py <this zip>\n",
        )

    background.add_task(shutil.rmtree, tmp_dir, True)
    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)
