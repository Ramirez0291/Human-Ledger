"""数据模型。

约束：
1. 所有金额字段一律为 **整数日元**，禁止浮点。
2. 所有业务表带 user_id，为将来扩多用户预留（需求书 D2）。
3. 商家名同时保存 merchant_raw（原文）与 merchant_norm（规范化结果），
   后者是去重与学习的比对基准（需求书 F4.1）。
"""

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
    """统一以 VARCHAR + CHECK 存储枚举。"""
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
# 用户与设置
# --------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class AppSetting(Base, TimestampMixin):
    """键值设置表。value 以 JSON 文本存储；is_secret 标记的项不回传给前端明文。"""

    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_settings_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# --------------------------------------------------------------------------
# 账户
# --------------------------------------------------------------------------


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[AccountType] = mapped_column(_enum(AccountType, "account_type"), nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(String(128))

    # 期初余额与起算日：当前余额 = 期初余额 + 其后所有交易的净额
    opening_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opening_date: Mapped[Optional[dt.date]] = mapped_column(Date)

    # 信用卡专用：締め日 / 支払日，用于「本月刷卡→下月扣款」的现金流预测
    closing_day: Mapped[Optional[int]] = mapped_column(Integer)
    payment_day: Mapped[Optional[int]] = mapped_column(Integer)

    color: Mapped[Optional[str]] = mapped_column(String(16))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class BalanceSnapshot(Base, TimestampMixin):
    """余额快照与对账记录（需求书 F1 / 附录 A.3.6）。

    computed_balance 为系统按流水算出的余额，balance 为用户录入或截图识别到的
    实际余额，diff != 0 即提示可能漏记。
    """

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
# 类目（两级）
# --------------------------------------------------------------------------


class Category(Base, TimestampMixin):
    """类目。名称不存在本表，而在 category_names 中按语言存储（需求书 F10）。"""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_categories_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    # i18n 词条键，如 "category.food" / "category.food.dining"
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
    """类目的多语言名称。新增一种语言只需插入一批行，无需改表。"""

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
# 交易
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
    # 部分来源带时分（如 PayPay「2026年5月26日 0時54分」），可用于区分同日同额交易
    time: Mapped[Optional[dt.time]] = mapped_column()
    direction: Mapped[Direction] = mapped_column(_enum(Direction, "direction"), nullable=False)
    # 整数日元，恒为非负；方向由 direction 表达
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

    # ---- 分期付款（需求书附录 A.5.1）----
    # 口径已确认：amount 存**当期金额**（本月实际现金流），下面三个字段仅作
    # 参考信息保留，不参与任何合计，避免 48 回払い 的总额被当月重复计入。
    installment_current: Mapped[Optional[int]] = mapped_column(Integer)  # 第几期
    installment_total: Mapped[Optional[int]] = mapped_column(Integer)  # 共几期
    installment_total_amount: Mapped[Optional[int]] = mapped_column(Integer)  # 总额

    # sha1(date|direction|amount|merchant_norm)，判重主键
    fingerprint: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # 转账的两条记录共享此 id，统计时整体排除
    transfer_group_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)

    # 不计入月度分析：搬家、买电脑、住院这类一次性大额 / 意外开支。
    # 只影响报表的「日常开支」口径，余额与交易列表照常计入
    exclude_from_analysis: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    # 软删除：保留 30 天回收站
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), index=True)


# --------------------------------------------------------------------------
# 导入（截图 / CSV）
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
    """导入的来源文件。

    表名沿用 import_images，但也存放文本粘贴（file_path 为空）与将来的 CSV：
    sha256 用于「同一份来源重复导入」检测，对任何来源都成立。
    """

    __tablename__ = "import_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(512))
    # 同一张图重复上传时直接命中，无需再走识别
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    # 自动识别出的来源机构，如 "smbc_olive" / "rakuten_card" / "paypay"
    detected_institution: Mapped[Optional[str]] = mapped_column(String(64))
    ocr_provider: Mapped[Optional[str]] = mapped_column(String(32))
    ocr_raw_json: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)


class StagedTransaction(Base, TimestampMixin):
    """待确认区的交易（需求书 F3.4）。

    识别结果一律先落在此表，人工确认后才写入 transactions。
    """

    __tablename__ = "staged_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    source_image_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_images.id", ondelete="SET NULL")
    )

    # ---- 业务字段（与 transactions 对应）----
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

    # ---- 识别与判定元信息 ----
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    category_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    category_source: Mapped[CategorySource] = mapped_column(
        _enum(CategorySource, "category_source"), default=CategorySource.none, nullable=False
    )
    # 日期由「向上继承」或年份推断得出（附录 A.3.1 / A.3.2），需在 UI 上标注
    date_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    dup_status: Mapped[DupStatus] = mapped_column(
        _enum(DupStatus, "dup_status"), default=DupStatus.none, nullable=False
    )
    # 人类可读的判重理由，如「与 9/5 的 ローソン ¥580 重复」——不做黑箱
    dup_reason: Mapped[Optional[str]] = mapped_column(Text)
    dup_ref_id: Mapped[Optional[int]] = mapped_column(Integer)
    # L1/L2 合并了多少条同指纹记录（可展开还原）
    merged_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 该行在来源截图中的位置，供 UI 高亮核对，格式 "x,y,w,h"
    bbox: Mapped[Optional[str]] = mapped_column(String(64))
    # 识别层看到的原始文本（逐字），便于核对与排查
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    # 被排除的行（如 PayPay「支払い失敗」）保留在此并说明原因，不静默丢弃
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclude_reason: Mapped[Optional[str]] = mapped_column(Text)
    # L1/L2 合并：被合并进哪一行。展开还原时清空此字段并取消 excluded
    merged_into_id: Mapped[Optional[int]] = mapped_column(Integer)

    # 交易后残高（三井住友銀行等逐行提供），确认入账时可自动生成对账快照
    balance_after: Mapped[Optional[int]] = mapped_column(Integer)

    # 分类引擎判断这像一笔转账（信用卡还款、IC 充值、ATM）；用户指定对方账户后，
    # 确认时生成成对的转账记录而非单笔支出
    transfer_hint: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counterpart_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL")
    )

    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --------------------------------------------------------------------------
# 分类规则与学习
# --------------------------------------------------------------------------


class CategoryRule(Base, TimestampMixin):
    """用户规则，判别链第 1 层（需求书 F5.2）。"""

    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    match_type: Mapped[MatchType] = mapped_column(_enum(MatchType, "match_type"), nullable=False)
    pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    # 可选：仅对某账户生效
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MerchantMemory(Base, TimestampMixin):
    """商家记忆，判别链第 2 层。用户每次改分类即在此回写。"""

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
# 预算与固定支出
# --------------------------------------------------------------------------


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "year_month", name="uq_budgets_user_cat_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # NULL 表示总预算
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-09"
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)


class RecurringRule(Base, TimestampMixin):
    """固定支出（需求书 F8）。"""

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
    # 金额可变项（水电燃气）：入账时按上次金额预填，允许修改
    amount_is_variable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    freq: Mapped[RecurringFreq] = mapped_column(
        _enum(RecurringFreq, "recurring_freq"), default=RecurringFreq.monthly, nullable=False
    )
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 年度/分期项适用，逗号分隔的月份列表，如住民税 "6,8,10,1"
    months: Mapped[Optional[str]] = mapped_column(String(32))

    mode: Mapped[RecurringMode] = mapped_column(
        _enum(RecurringMode, "recurring_mode"), default=RecurringMode.remind, nullable=False
    )
    reminder_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_due_date: Mapped[Optional[dt.date]] = mapped_column(Date, index=True)
    last_generated_at: Mapped[Optional[dt.date]] = mapped_column(Date)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
