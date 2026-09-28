from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import BatchStatus, CategorySource, Direction, DupStatus, MatchType, TxnSource


class TextImportRequest(BaseModel):
    """文本粘贴导入：把截图上的文字按行贴进来（等价于本地 OCR 的输出）。"""

    account_id: int
    text: str = Field(min_length=1, max_length=200_000)
    # 支払月锚点（YYYY-MM），用于无年份日期的年份推断；不传则从文本中的年月标题推断
    statement_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    # 已有草稿批次时追加到该批次（多张截图合并判重），否则新建
    batch_id: int | None = None


class StagedRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    account_id: int | None
    account_name: str = ""
    date: dt.date | None
    time: dt.time | None
    direction: Direction | None
    amount: int | None
    merchant_raw: str
    merchant_norm: str
    category_id: int | None
    category_name: str | None = None
    category_icon: str | None = None
    category_color: str | None = None
    memo: str | None
    confidence: float
    category_confidence: float
    category_source: CategorySource
    date_inferred: bool
    dup_status: DupStatus
    dup_reason: str | None
    dup_ref_id: int | None
    merged_count: int
    excluded: bool
    exclude_reason: str | None
    merged_into_id: int | None
    balance_after: int | None
    transfer_hint: bool
    counterpart_account_id: int | None
    is_selected: bool
    installment_current: int | None
    installment_total: int | None
    installment_total_amount: int | None
    raw_text: str | None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: TxnSource
    status: BatchStatus
    file_count: int
    note: str | None
    created_at: dt.datetime
    # 概览计数
    total_rows: int = 0
    selected_rows: int = 0
    excluded_rows: int = 0
    duplicate_rows: int = 0
    maybe_rows: int = 0
    # 已确认 / 已撤销批次：入账概况（导入记录用）
    ledger_rows: int = 0
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    account_names: list[str] = Field(default_factory=list)
    overlap_rows: int = 0
    redundant_rows: int = 0
    overlaps: dict[int, int] = Field(default_factory=dict)


class BatchDetail(BaseModel):
    batch: BatchOut
    rows: list[StagedRowOut]
    warnings: list[str] = Field(default_factory=list)
    detected_balance: int | None = None
    statement_month: str | None = None
    # 同一份文本之前导入过
    previously_imported: bool = False


class StagedRowUpdate(BaseModel):
    account_id: int | None = None
    date: dt.date | None = None
    direction: Direction | None = None
    amount: int | None = Field(default=None, ge=0)
    merchant_raw: str | None = Field(default=None, max_length=512)
    category_id: int | None = None
    memo: str | None = None
    is_selected: bool | None = None
    counterpart_account_id: int | None = None
    # 显式清空对方账户
    clear_counterpart: bool = False
    # 显式清空类别
    clear_category: bool = False
    # 改了类别时，把同批次里同一商家（或同品牌）且尚未由用户改过的行一起改掉。
    # 这是待确认区提速的关键：一个月 15 笔 RakutenTurbo 只需改一次。
    apply_to_similar: bool = True


class StagedRowPatchOut(BaseModel):
    row: StagedRowOut
    # 因 apply_to_similar 连带更新的其他行
    affected: list[StagedRowOut] = []


class BulkUpdate(BaseModel):
    row_ids: list[int] = Field(min_length=1)
    category_id: int | None = None
    account_id: int | None = None
    is_selected: bool | None = None


class BatchActionOut(BaseModel):
    removed: int
    batch: "BatchOut"


class ConfirmOut(BaseModel):
    imported: int
    transfers: int
    skipped_unselected: int
    skipped_excluded: int
    skipped_incomplete: int
    skipped_duplicate: int = 0
    reconcile: dict | None
    warnings: list[str]


# ---- 规则 ----


class RuleCreate(BaseModel):
    match_type: MatchType
    pattern: str = Field(min_length=1, max_length=512)
    category_id: int
    account_id: int | None = None
    priority: int = 0
    enabled: bool = True


class RuleUpdate(BaseModel):
    match_type: MatchType | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=512)
    category_id: int | None = None
    account_id: int | None = None
    clear_account: bool = False
    priority: int | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_type: MatchType
    pattern: str
    category_id: int
    category_name: str | None = None
    account_id: int | None
    priority: int
    enabled: bool


# ---- CSV ----


class CsvFilePreview(BaseModel):
    filename: str
    encoding: str
    profile: str | None
    profile_name: str | None
    account_kind: str | None
    header: list[str]
    sample: list[list[str]]
    row_count: int
    mapping: dict | None
    statement_month: str | None
    previously_imported: bool
    warnings: list[str] = Field(default_factory=list)


class CsvPreviewOut(BaseModel):
    files: list[CsvFilePreview]
    suggested_account_id: int | None = None
