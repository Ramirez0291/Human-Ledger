"""预算（需求书 F7）：默认预算、特别预算、月度状态与月末预测。"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.clock import local_today
from app.core.deps import get_current_user
from app.db.enums import CategoryType
from app.db.models import Budget, Category, SpecialBudget, User
from app.db.session import get_db
from app.regions import region_of
from app.schemas.budgets import BudgetOut, BudgetUpsert, SpecialBudgetIn, SpecialBudgetPatch
from app.services import budgets as svc

router = APIRouter(prefix="/budgets", tags=["budgets"])

_YM = r"^\d{4}-(0[1-9]|1[0-2])$"


def _today(as_of: dt.date | None, user: User) -> dt.date:
    return as_of or local_today(region_of(user).timezone)


def _expense_category(db: Session, user: User, category_id: int | None) -> None:
    if category_id is None:
        return
    c = db.get(Category, category_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(status_code=404, detail="category_not_found")
    if c.type != CategoryType.expense:
        raise HTTPException(status_code=400, detail="budget_category_not_expense")


def _budget_out(db: Session, user: User, rows: list[Budget]) -> list[BudgetOut]:
    meta = svc.category_meta(db, {b.category_id for b in rows if b.category_id}, user.locale)
    return [
        BudgetOut(
            id=b.id,
            category_id=b.category_id,
            amount=b.amount,
            alert_threshold_pct=b.alert_threshold_pct,
            **meta.get(b.category_id or -1, {}),
        )
        for b in rows
    ]


@router.get("")
def list_budgets(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    sbs = svc.specials(db, user.id)
    meta = svc.category_meta(db, {s.category_id for s in sbs if s.category_id}, user.locale)
    return {
        "defaults": _budget_out(db, user, svc.defaults(db, user.id)),
        "specials": [svc.special_dict(s, meta) for s in sbs],
    }


@router.put("/default", response_model=BudgetOut)
def upsert_default(
    payload: BudgetUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BudgetOut:
    """设置 / 修改默认预算。每个类目（与总额）只有一条，重复提交即修改。"""
    _expense_category(db, user, payload.category_id)
    same_category = (
        Budget.category_id.is_(None)
        if payload.category_id is None
        else Budget.category_id == payload.category_id
    )
    row = (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.year_month.is_(None), same_category)
        .first()
    )
    if row is None:
        row = Budget(user_id=user.id, category_id=payload.category_id, year_month=None, amount=0)
        db.add(row)
    row.amount = payload.amount
    row.alert_threshold_pct = payload.alert_threshold_pct
    db.commit()
    db.refresh(row)
    return _budget_out(db, user, [row])[0]


@router.delete("/default/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_default(
    budget_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(Budget, budget_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="budget_not_found")
    db.delete(row)
    db.commit()


@router.get("/suggest")
def suggest(
    as_of: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按过去的习惯给一套起步预算（用户确认后才保存）。"""
    region = region_of(user)
    steps = (region.budget_step_category, region.budget_step_total)
    return svc.suggest(db, user.id, user.locale, _today(as_of, user), steps)


@router.get("/status")
def budget_status(
    year_month: str | None = Query(default=None, pattern=_YM),
    as_of: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    today = _today(as_of, user)
    return svc.status(db, user.id, user.locale, year_month or today.strftime("%Y-%m"), today)


# --------------------------------------------------------------------------
# 特别预算
# --------------------------------------------------------------------------


def _owned_special(db: Session, user: User, special_id: int) -> SpecialBudget:
    row = db.get(SpecialBudget, special_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="special_budget_not_found")
    return row


def _special_out(db: Session, user: User, row: SpecialBudget) -> dict:
    meta = svc.category_meta(db, {row.category_id} if row.category_id else set(), user.locale)
    return svc.special_dict(row, meta)


@router.post("/special", status_code=status.HTTP_201_CREATED)
def create_special(
    payload: SpecialBudgetIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _expense_category(db, user, payload.category_id)
    row = SpecialBudget(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _special_out(db, user, row)


@router.patch("/special/{special_id}")
def update_special(
    special_id: int,
    payload: SpecialBudgetPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = _owned_special(db, user, special_id)
    data = payload.model_dump(exclude_unset=True)
    clear = data.pop("clear_category", False)
    if data.get("category_id") is not None:
        _expense_category(db, user, data["category_id"])
    for key, value in data.items():
        # 备注允许清空，其余字段传 null 视为「不改」
        if value is None and key != "memo":
            continue
        setattr(row, key, value)
    if clear:
        row.category_id = None
    if row.date_to < row.date_from:
        raise HTTPException(status_code=422, detail="date_to_before_date_from")
    db.commit()
    db.refresh(row)
    return _special_out(db, user, row)


@router.delete("/special/{special_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_special(
    special_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    db.delete(_owned_special(db, user, special_id))
    db.commit()
