"""元数据与总览：系统信息、OCR 方案状态、月度概览。

类目接口已移至 app/api/routers/categories.py。
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.clock import local_today
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
from app.regions import region_of
from app.services.balances import compute_balances, monthly_summary
from app.services.ocr.providers import provider_status
from app.services.compliance import tension
from app.services.preferences import LEDGER_MODES, ledger_mode, set_pref

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/system")
def system_info(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """数据库与迁移状态。供「关于」页与里程碑验证界面展示。"""
    insp = inspect(db.get_bind())
    tables = [t for t in insp.get_table_names() if t != "alembic_version"]
    # 用 create_all 建的库（测试、手动初始化）没有 alembic_version 表，不该因此 500
    revision = (
        db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if "alembic_version" in insp.get_table_names()
        else None
    )
    return {
        "table_count": len(tables),
        "tables": sorted(tables),
        "migration_revision": revision,
        # 「今天」按用户地区包的时区算（app/core/clock）
        "timezone": region_of(user).timezone,
        "database": "sqlite" if settings.resolved_database_url.startswith("sqlite") else "other",
        # 只有实例所有者能下载整库备份，前端据此决定是否显示备份卡片
        "is_owner": user.is_owner,
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
    year_month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """总览页数据：月度收支、账户余额、按类目的支出构成、最近交易、对账提醒。"""
    today = local_today(region_of(user).timezone)
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
    # 轻松模式不提示差额：余额本来就以最近一次真实余额为准，漏记几笔很正常
    alerts = []
    for a in accounts if ledger_mode(db, user.id) == "strict" else []:
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


# --------------------------------------------------------------------------
# 用户偏好
# --------------------------------------------------------------------------


class PreferencesIn(BaseModel):
    ledger_mode: str | None = None


@router.get("/preferences")
def get_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return {"ledger_mode": ledger_mode(db, user.id)}


@router.patch("/preferences")
def update_preferences(
    payload: PreferencesIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.ledger_mode is not None:
        if payload.ledger_mode not in LEDGER_MODES:
            raise HTTPException(status_code=422, detail="invalid_ledger_mode")
        set_pref(db, user.id, "ledger_mode", payload.ledger_mode)
    db.commit()
    return {"ledger_mode": ledger_mode(db, user.id)}


@router.get("/compliance")
def compliance(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """合规模式的账面紧张度（0 平静 … 4 失控）。轻松模式下恒为 0，界面不渲染任何紧张元素。"""
    if ledger_mode(db, user.id) != "strict":
        return {"level": 0, "total_abs_diff": 0, "monthly_base": 0, "ratio": 0, "gaps": 0, "accounts": [], "mode": "relaxed"}
    return {**tension(db, user.id), "mode": "strict"}
