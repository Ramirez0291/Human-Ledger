from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import AccountType, CategoryType, Direction, TxnSource

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class AccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: AccountType
    institution: str | None = Field(default=None, max_length=128)
    opening_balance: int = 0
    opening_date: dt.date | None = None
    closing_day: int | None = Field(default=None, ge=1, le=31)
    payment_day: int | None = Field(default=None, ge=1, le=31)
    color: str | None = Field(default=None, max_length=16)
    sort_order: int = 0


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    type: AccountType | None = None
    institution: str | None = Field(default=None, max_length=128)
    opening_balance: int | None = None
    opening_date: dt.date | None = None
    closing_day: int | None = Field(default=None, ge=1, le=31)
    payment_day: int | None = Field(default=None, ge=1, le=31)
    color: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None
    is_archived: bool | None = None


class AccountOut(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_archived: bool
    balance: int = 0
    transaction_count: int = 0
    last_reconcile_diff: int | None = None
    last_reconcile_date: dt.date | None = None


class ReconcileRequest(BaseModel):
    date: dt.date
    actual_balance: int
    note: str | None = None


class ReconcileOut(BaseModel):
    date: dt.date
    actual_balance: int
    computed_balance: int
    diff: int


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    parent_id: int | None = None
    type: CategoryType
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    names: dict[str, str] = Field(min_length=1)


class CategoryUpdate(BaseModel):
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    names: dict[str, str] | None = None
    is_hidden: bool | None = None
    sort_order: int | None = None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class TransactionCreate(BaseModel):
    account_id: int
    date: dt.date
    time: dt.time | None = None
    direction: Direction
    amount: int = Field(ge=0)
    merchant_raw: str = Field(default="", max_length=512)
    category_id: int | None = None
    memo: str | None = None
    installment_current: int | None = Field(default=None, ge=1)
    installment_total: int | None = Field(default=None, ge=1)
    installment_total_amount: int | None = Field(default=None, ge=0)
    exclude_from_analysis: bool = False

    @field_validator("direction")
    @classmethod
    def _no_transfer_here(cls, v: Direction) -> Direction:
        if v in (Direction.transfer_in, Direction.transfer_out):
            raise ValueError("Use /transactions/transfer for transfers")
        return v


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    date: dt.date | None = None
    time: dt.time | None = None
    direction: Direction | None = None
    amount: int | None = Field(default=None, ge=0)
    merchant_raw: str | None = Field(default=None, max_length=512)
    category_id: int | None = None
    memo: str | None = None
    installment_current: int | None = Field(default=None, ge=1)
    installment_total: int | None = Field(default=None, ge=1)
    installment_total_amount: int | None = Field(default=None, ge=0)
    exclude_from_analysis: bool | None = None


class ConvertToTransfer(BaseModel):
    counterpart_account_id: int


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    date: dt.date
    amount: int = Field(gt=0)
    memo: str | None = None
    fee: int = Field(default=0, ge=0)
    fee_category_id: int | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str = ""
    date: dt.date
    time: dt.time | None
    direction: Direction
    amount: int
    merchant_raw: str
    merchant_norm: str
    category_id: int | None
    category_key: str | None = None
    category_name: str | None = None
    category_icon: str | None = None
    category_color: str | None = None
    memo: str | None
    source: TxnSource
    transfer_group_id: str | None
    installment_current: int | None
    installment_total: int | None
    installment_total_amount: int | None
    exclude_from_analysis: bool = False
    deleted_at: dt.datetime | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int
    sum_income: int
    sum_expense: int


class CategorySuggestion(BaseModel):
    category_id: int | None
    confidence: float
