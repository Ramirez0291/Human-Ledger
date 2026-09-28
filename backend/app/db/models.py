"""Data models. All amounts are integer yen. Every business table is scoped by user_id."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import (
    AccountType,
    BatchStatus,
    CategorySource,
    CategoryType,
    Direction,
    DupStatus,
    MatchType,
    RecurringFreq,
    RecurringMode,
    SnapshotSource,
    TxnSource,
)


def _enum(py_enum, name: str):
    return Enum(py_enum, native_enum=False, validate_strings=True, name=name)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class AppSetting(Base, TimestampMixin):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_settings_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[AccountType] = mapped_column(_enum(AccountType, "account_type"), nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(String(128))

    opening_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opening_date: Mapped[Optional[dt.date]] = mapped_column(Date)

    closing_day: Mapped[Optional[int]] = mapped_column(Integer)
    payment_day: Mapped[Optional[int]] = mapped_column(Integer)

    color: Mapped[Optional[str]] = mapped_column(String(16))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class BalanceSnapshot(Base, TimestampMixin):
    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_balance: Mapped[Optional[int]] = mapped_column(Integer)
    diff: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[SnapshotSource] = mapped_column(
        _enum(SnapshotSource, "snapshot_source"), default=SnapshotSource.manual, nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_categories_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[CategoryType] = mapped_column(_enum(CategoryType, "category_type"), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(64))
    color: Mapped[Optional[str]] = mapped_column(String(16))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    names: Mapped[list["CategoryName"]] = relationship(
        back_populates="category", cascade="all, delete-orphan", lazy="selectin"
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[Optional["Category"]] = relationship(
        back_populates="children", remote_side="Category.id"
    )


class CategoryName(Base):
    __tablename__ = "category_names"
    __table_args__ = (
        UniqueConstraint("category_id", "locale", name="uq_category_names_category_locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    category: Mapped["Category"] = relationship(back_populates="names")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_fingerprint", "fingerprint"),
        Index("ix_transactions_merchant_norm", "merchant_norm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )

    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    time: Mapped[Optional[dt.time]] = mapped_column()
    direction: Mapped[Direction] = mapped_column(_enum(Direction, "direction"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    merchant_raw: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    merchant_norm: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    memo: Mapped[Optional[str]] = mapped_column(Text)

    source: Mapped[TxnSource] = mapped_column(
        _enum(TxnSource, "txn_source"), default=TxnSource.manual, nullable=False
    )
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    source_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_images.id", ondelete="SET NULL")
    )
    recurring_rule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recurring_rules.id", ondelete="SET NULL")
    )

    # Installments: amount is the current instalment; the fields below are informational only.
    installment_current: Mapped[Optional[int]] = mapped_column(Integer)
    installment_total: Mapped[Optional[int]] = mapped_column(Integer)
    installment_total_amount: Mapped[Optional[int]] = mapped_column(Integer)

    # sha1(date|direction|amount|merchant_norm), used for dedup
    fingerprint: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # Both legs of a transfer share this id
    transfer_group_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)

    # Excluded from reports only; balances and lists are unaffected
    exclude_from_analysis: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), index=True)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[TxnSource] = mapped_column(_enum(TxnSource, "batch_source"), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        _enum(BatchStatus, "batch_status"), default=BatchStatus.draft, nullable=False
    )
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)


class ImportImage(Base, TimestampMixin):
    __tablename__ = "import_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    detected_institution: Mapped[Optional[str]] = mapped_column(String(64))
    ocr_provider: Mapped[Optional[str]] = mapped_column(String(32))
    ocr_raw_json: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)


class StagedTransaction(Base, TimestampMixin):
    __tablename__ = "staged_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    source_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_images.id", ondelete="SET NULL")
    )

    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    date: Mapped[Optional[dt.date]] = mapped_column(Date)
    time: Mapped[Optional[dt.time]] = mapped_column()
    direction: Mapped[Optional[Direction]] = mapped_column(_enum(Direction, "staged_direction"))
    amount: Mapped[Optional[int]] = mapped_column(Integer)
    merchant_raw: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    merchant_norm: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    memo: Mapped[Optional[str]] = mapped_column(Text)
    installment_current: Mapped[Optional[int]] = mapped_column(Integer)
    installment_total: Mapped[Optional[int]] = mapped_column(Integer)
    installment_total_amount: Mapped[Optional[int]] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(40), default="", index=True, nullable=False)

    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    category_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    category_source: Mapped[CategorySource] = mapped_column(
        _enum(CategorySource, "category_source"), default=CategorySource.none, nullable=False
    )
    date_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    dup_status: Mapped[DupStatus] = mapped_column(
        _enum(DupStatus, "dup_status"), default=DupStatus.none, nullable=False
    )
    dup_reason: Mapped[Optional[str]] = mapped_column(Text)
    dup_ref_id: Mapped[Optional[int]] = mapped_column(Integer)
    merged_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    bbox: Mapped[Optional[str]] = mapped_column(String(64))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclude_reason: Mapped[Optional[str]] = mapped_column(Text)
    merged_into_id: Mapped[Optional[int]] = mapped_column(Integer)

    balance_after: Mapped[Optional[int]] = mapped_column(Integer)

    transfer_hint: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counterpart_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL")
    )

    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class CategoryRule(Base, TimestampMixin):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    match_type: Mapped[MatchType] = mapped_column(_enum(MatchType, "match_type"), nullable=False)
    pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MerchantMemory(Base, TimestampMixin):
    __tablename__ = "merchant_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant_norm", name="uq_merchant_memory_user_merchant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant_norm: Mapped[str] = mapped_column(String(512), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    hit_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "year_month", name="uq_budgets_user_cat_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-09"
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)


class RecurringRule(Base, TimestampMixin):
    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    direction: Mapped[Direction] = mapped_column(
        _enum(Direction, "recurring_direction"), default=Direction.expense, nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_is_variable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    freq: Mapped[RecurringFreq] = mapped_column(
        _enum(RecurringFreq, "recurring_freq"), default=RecurringFreq.monthly, nullable=False
    )
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    months: Mapped[Optional[str]] = mapped_column(String(32))

    mode: Mapped[RecurringMode] = mapped_column(
        _enum(RecurringMode, "recurring_mode"), default=RecurringMode.remind, nullable=False
    )
    reminder_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_due_date: Mapped[Optional[dt.date]] = mapped_column(Date, index=True)
    last_generated_at: Mapped[Optional[dt.date]] = mapped_column(Date)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
