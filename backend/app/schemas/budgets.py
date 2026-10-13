from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator

from app.db.enums import SpecialBudgetKind


class BudgetUpsert(BaseModel):
    """设置默认预算（每月沿用）。category_id 为空 = 总预算。"""

    category_id: int | None = None
    amount: int = Field(ge=0, le=100_000_000)
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)


class BudgetOut(BaseModel):
    id: int
    category_id: int | None
    amount: int
    alert_threshold_pct: int
    name: str | None = None
    icon: str | None = None
    color: str | None = None


class SpecialBudgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: SpecialBudgetKind = SpecialBudgetKind.other
    amount: int = Field(gt=0, le=100_000_000)
    date_from: dt.date
    date_to: dt.date
    category_id: int | None = None
    memo: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _range(self) -> "SpecialBudgetIn":
        if self.date_to < self.date_from:
            raise ValueError("date_to_before_date_from")
        if (self.date_to - self.date_from).days > 366:
            raise ValueError("range_too_long")
        return self


class SpecialBudgetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: SpecialBudgetKind | None = None
    amount: int | None = Field(default=None, gt=0, le=100_000_000)
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    category_id: int | None = None
    clear_category: bool = False
    memo: str | None = Field(default=None, max_length=1000)
