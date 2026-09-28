"""元数据与总览：系统信息、OCR 方案状态、月度概览。

类目接口已移至 app/api/routers/categories.py。
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.enums import Direction
from app.db.models import (
    Account,
    BalanceSnapshot,
    Category,
    CategoryName,
    Transaction,
    User,
)
from app.db.session import get_db
from app.services.balances import compute_balances, monthly_summary
from app.services.ocr.providers import provider_status

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/system")
def system_info(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001
) -> dict:
    """数据库与迁移状态。供「关于」页与里程碑验证界面展示。"""
    insp = inspect(db.get_bind())
    tables = [t for t in insp.get_table_names() if t != "alembic_version"]
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "table_count": len(tables),
        "tables": sorted(tables),
        "migration_revision": revision,
        "timezone": settings.timezone,
        "database": "sqlite" if settings.resolved_database_url.startswith("sqlite") else "other",
    }


@router.get("/ocr/providers")
def ocr_providers(user: User = Depends(get_current_user)) -> dict:  # noqa: ARG001
    """截图识别方案的配置状态。M0/M1 阶段三者均未接入，此处如实反映。"""
    return {
        "active": settings.ocr_provider,
        "providers": provider_status(),
        "note_key": "ocr.reason.plannedM2",
    }


@router.get("/summary")
def summary(
    year_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """总览页数据：月度收支、账户余额、按类目的支出构成、最近交易、对账提醒。"""
    today = dt.date.today()
    ym = year_month or f"{today.year:04d}-{today.month:02d}"

    totals = monthly_summary(db, user.id, ym)

    start = dt.date.fromisoformat(f"{ym}-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

    # ---- 账户余额 ----
    balances = compute_balances(db, user.id)
    accounts = (
        db.query(Account)
        .filter(Account.user_id == user.id, Account.is_archived.is_(False))
        .order_by(Account.sort_order, Account.id)
        .all()
    )
    account_rows = [
        {
            "id": a.id,
            "name": a.name,
            "type": a.type.value,
            "color": a.color,
            "balance": balances.get(a.id, a.opening_balance),
        }
        for a in accounts
    ]

    # ---- 本月支出按大分類构成 ----
    # 子类目的支出上卷到其父类目，避免总览页出现几十个细项
    parent_expr = func.coalesce(Category.parent_id, Category.id)
    rows = db.execute(
        select(parent_expr.label("top_id"), func.sum(Transaction.amount))
        .join(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.direction == Direction.expense,
            Transaction.date >= start,
            Transaction.date < end,
        )
        .group_by("top_id")
    ).all()

    breakdown: list[dict] = []
    if rows:
        top_ids = [int(r[0]) for r in rows]
        cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(top_ids)).all()}
        names = {
            cn.category_id: cn.name
            for cn in db.query(CategoryName)
            .filter(CategoryName.category_id.in_(top_ids), CategoryName.locale == user.locale)
            .all()
        }
        for top_id, total in rows:
            c = cats.get(int(top_id))
            if c is None:
                continue
            breakdown.append(
                {
                    "category_id": c.id,
                    "key": c.key,
                    "name": names.get(c.id, c.key),
                    "icon": c.icon,
                    "color": c.color,
                    "amount": int(total),
                }
            )
        breakdown.sort(key=lambda x: x["amount"], reverse=True)

    # 未分类支出单列，提醒用户去补分类
    uncategorized = int(
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.direction == Direction.expense,
            Transaction.category_id.is_(None),
            Transaction.date >= start,
            Transaction.date < end,
        )
        .scalar()
        or 0
    )

    # ---- 对账提醒 ----
    alerts = []
    for a in accounts:
        last = db.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == a.id)
            .order_by(BalanceSnapshot.date.desc(), BalanceSnapshot.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is not None and last.diff:
            alerts.append(
                {
                    "account_id": a.id,
                    "account_name": a.name,
                    "date": last.date.isoformat(),
                    "diff": last.diff,
                }
            )

    return {
        "year_month": ym,
        "income": totals["income"],
        "expense": totals["expense"],
        "net": totals["net"],
        "accounts": account_rows,
        "total_balance": sum(r["balance"] for r in account_rows),
        "expense_breakdown": breakdown,
        "uncategorized_expense": uncategorized,
        "reconcile_alerts": alerts,
        "transaction_count": int(
            db.query(func.count(Transaction.id))
            .filter(
                Transaction.user_id == user.id,
                Transaction.deleted_at.is_(None),
                Transaction.date >= start,
                Transaction.date < end,
            )
            .scalar()
            or 0
        ),
    }
