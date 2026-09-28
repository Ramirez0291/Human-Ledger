from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import AccountType, CategoryType, Direction, TxnSource

# --------------------------------------------------------------------------
# 账户
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
    # 最近一次对账的差额；非 0 说明可能漏记
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
# 类目
# --------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    parent_id: int | None = None
    type: CategoryType
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    # 用户自建类目的名称：至少提供一种语言，其余语言回退显示它
    names: dict[str, str] = Field(min_length=1)


class CategoryUpdate(BaseModel):
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    names: dict[str, str] | None = None
    is_hidden: bool | None = None
    sort_order: int | None = None


# --------------------------------------------------------------------------
# 交易
# --------------------------------------------------------------------------


class TransactionCreate(BaseModel):
    account_id: int
    date: dt.date
    time: dt.time | None = None
    # 转账请使用 /transactions/transfer，此处仅接受收支
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
            raise ValueError("转账请使用 /transactions/transfer 接口，以保证两条腿成对生成")
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
    """账户间转账：ATM 取现、PayPay 充值、信用卡还款、交通 IC 充值等。

    生成两条共享 transfer_group_id 的记录，且不计入收支统计。
    """

    from_account_id: int
    to_account_id: int
    date: dt.date
    amount: int = Field(gt=0)
    memo: str | None = None
    # 手续费（如海外汇款），作为一笔独立支出记在转出账户上
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
    # 当前筛选条件下的合计（不含转账）
    sum_income: int
    sum_expense: int


class CategorySuggestion(BaseModel):
    category_id: int | None
    confidence: float
