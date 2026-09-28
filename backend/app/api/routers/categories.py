from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.enums import CategoryType
from app.db.models import Category, CategoryName, Transaction, User
from app.db.session import get_db
from app.schemas.ledger import CategoryCreate, CategoryUpdate
from app.services.seed import SUPPORTED_LOCALES

router = APIRouter(prefix="/categories", tags=["categories"])


def _slugify(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z぀-ヿ一-鿿]+", "-", text).strip("-").lower()
    return s or "custom"


def _get_owned(db: Session, user: User, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=404, detail="category_not_found")
    return category


def _names_map(db: Session, category_ids: list[int]) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    if not category_ids:
        return out
    for row in db.query(CategoryName).filter(CategoryName.category_id.in_(category_ids)).all():
        out.setdefault(row.category_id, {})[row.locale] = row.name
    return out


@router.get("")
def list_categories(
    locale: str | None = Query(default=None),
    type: CategoryType | None = Query(default=None),
    include_hidden: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    target = locale if locale in SUPPORTED_LOCALES else user.locale
    fallback = settings.default_locale

    q = db.query(Category).filter(Category.user_id == user.id)
    if not include_hidden:
        q = q.filter(Category.is_hidden.is_(False))
    if type is not None:
        q = q.filter(Category.type == type)
    categories = q.order_by(Category.sort_order, Category.id).all()

    all_names = _names_map(db, [c.id for c in categories])

    def name_of(cid: int) -> str:
        m = all_names.get(cid, {})
        return m.get(target) or m.get(fallback) or next(iter(m.values()), "")

    by_parent: dict[int | None, list[Category]] = {}
    for c in categories:
        by_parent.setdefault(c.parent_id, []).append(c)

    def node(c: Category) -> dict:
        return {
            "id": c.id,
            "key": c.key,
            "parent_id": c.parent_id,
            "name": name_of(c.id),
            "names": all_names.get(c.id, {}),
            "type": c.type.value,
            "icon": c.icon,
            "color": c.color,
            "is_system": c.is_system,
            "is_hidden": c.is_hidden,
            "children": [node(x) for x in by_parent.get(c.id, [])],
        }

    return [node(c) for c in by_parent.get(None, [])]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    parent = None
    if payload.parent_id is not None:
        parent = _get_owned(db, user, payload.parent_id)
        if parent.parent_id is not None:
            raise HTTPException(status_code=400, detail="max_depth_two_levels")
        if parent.type != payload.type:
            raise HTTPException(status_code=400, detail="type_must_match_parent")

    base = _slugify(next(iter(payload.names.values())))
    key = f"{parent.key}.{base}" if parent else f"custom.{base}"
    suffix = 1
    while db.query(Category).filter(Category.user_id == user.id, Category.key == key).first():
        suffix += 1
        key = f"{parent.key}.{base}-{suffix}" if parent else f"custom.{base}-{suffix}"

    max_order = (
        db.query(func.coalesce(func.max(Category.sort_order), 0))
        .filter(Category.user_id == user.id, Category.parent_id == payload.parent_id)
        .scalar()
        or 0
    )

    category = Category(
        user_id=user.id,
        parent_id=payload.parent_id,
        key=key,
        type=payload.type,
        icon=payload.icon,
        color=payload.color or (parent.color if parent else None),
        is_system=False,
        sort_order=max_order + 1,
    )
    db.add(category)
    db.flush()

    default_name = next(iter(payload.names.values()))
    for loc in SUPPORTED_LOCALES:
        db.add(
            CategoryName(
                category_id=category.id,
                locale=loc,
                name=payload.names.get(loc, default_name),
            )
        )

    db.commit()
    db.refresh(category)
    names = _names_map(db, [category.id]).get(category.id, {})
    return {
        "id": category.id,
        "key": category.key,
        "parent_id": category.parent_id,
        "name": names.get(user.locale, default_name),
        "names": names,
        "type": category.type.value,
        "icon": category.icon,
        "color": category.color,
        "is_system": False,
        "is_hidden": False,
        "children": [],
    }


@router.patch("/{category_id}")
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    category = _get_owned(db, user, category_id)
    data = payload.model_dump(exclude_unset=True)

    for key in ("icon", "color", "is_hidden", "sort_order"):
        if key in data:
            setattr(category, key, data[key])

    if "names" in data and data["names"]:
        existing = {
            row.locale: row
            for row in db.query(CategoryName).filter(CategoryName.category_id == category.id).all()
        }
        for loc, name in data["names"].items():
            if loc not in SUPPORTED_LOCALES:
                continue
            if loc in existing:
                existing[loc].name = name
            else:
                db.add(CategoryName(category_id=category.id, locale=loc, name=name))

    db.commit()
    db.refresh(category)
    names = _names_map(db, [category.id]).get(category.id, {})
    return {
        "id": category.id,
        "key": category.key,
        "parent_id": category.parent_id,
        "name": names.get(user.locale) or category.key,
        "names": names,
        "type": category.type.value,
        "icon": category.icon,
        "color": category.color,
        "is_system": category.is_system,
        "is_hidden": category.is_hidden,
        "children": [],
    }


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    category = _get_owned(db, user, category_id)
    if category.is_system:
        raise HTTPException(status_code=409, detail="system_category_hide_instead")

    in_use = (
        db.query(func.count(Transaction.id))
        .filter(Transaction.category_id == category.id, Transaction.deleted_at.is_(None))
        .scalar()
        or 0
    )
    if in_use:
        raise HTTPException(status_code=409, detail="category_in_use")

    db.delete(category)
    db.commit()
