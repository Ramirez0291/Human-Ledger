"""用户分类规则（需求书 F5.2 第 1 层 / F5.3）。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.enums import MatchType
from app.db.models import Account, Category, CategoryName, CategoryRule, User
from app.db.session import get_db
from app.schemas.importing import RuleCreate, RuleOut, RuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"])


def _out(db: Session, user: User, rules: list[CategoryRule]) -> list[RuleOut]:
    ids = {r.category_id for r in rules}
    names: dict[int, str] = {}
    if ids:
        names = {
            cn.category_id: cn.name
            for cn in db.query(CategoryName)
            .filter(CategoryName.category_id.in_(ids), CategoryName.locale == user.locale)
            .all()
        }
    out = []
    for r in rules:
        item = RuleOut.model_validate(r)
        item.category_name = names.get(r.category_id)
        out.append(item)
    return out


def _validate(db: Session, user: User, category_id: int | None, account_id: int | None, match_type: MatchType | None, pattern: str | None) -> None:
    if category_id is not None:
        c = db.get(Category, category_id)
        if c is None or c.user_id != user.id:
            raise HTTPException(status_code=404, detail="category_not_found")
    if account_id is not None:
        a = db.get(Account, account_id)
        if a is None or a.user_id != user.id:
            raise HTTPException(status_code=404, detail="account_not_found")
    if match_type == MatchType.regex and pattern:
        try:
            re.compile(pattern)
        except re.error:
            raise HTTPException(status_code=400, detail="invalid_regex") from None


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[RuleOut]:
    rules = (
        db.query(CategoryRule)
        .filter(CategoryRule.user_id == user.id)
        .order_by(CategoryRule.priority.desc(), CategoryRule.id)
        .all()
    )
    return _out(db, user, rules)


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RuleOut:
    _validate(db, user, payload.category_id, payload.account_id, payload.match_type, payload.pattern)
    rule = CategoryRule(user_id=user.id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _out(db, user, [rule])[0]


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int,
    payload: RuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    rule = db.get(CategoryRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="rule_not_found")
    data = payload.model_dump(exclude_unset=True)
    _validate(
        db,
        user,
        data.get("category_id"),
        data.get("account_id"),
        data.get("match_type", rule.match_type),
        data.get("pattern", rule.pattern),
    )
    for key in ("match_type", "pattern", "category_id", "account_id", "priority", "enabled"):
        if key in data and data[key] is not None:
            setattr(rule, key, data[key])
    if payload.clear_account:
        rule.account_id = None
    db.commit()
    db.refresh(rule)
    return _out(db, user, [rule])[0]


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_rule(
    rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    rule = db.get(CategoryRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="rule_not_found")
    db.delete(rule)
    db.commit()
