"""截图识别的统一接口（需求书 D1 / F3.2）。

M0 阶段仅定义契约，不接入任何实现。之所以现在就把结构定死，是因为
附录 A 的样本分析已经暴露了若干必须由识别层输出的字段（排除原因、
日期是否为推断、逐行残高），事后补会导致整条管道返工。

三种实现共用此接口：
- LocalOcrExtractor   本地 OCR 引擎        （M2）
- LlmVisionExtractor  云端多模态模型        （M2）
- ReceiptExtractor    纸质收据解析          （v2，需求书 D7 的架构预留）
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawTransaction:
    """识别层输出的一条原始交易，尚未规范化、判重、分类。"""

    # ---- 核心字段 ----
    date: dt.date | None = None
    time: dt.time | None = None
    amount: int | None = None  # 整数日元
    merchant_raw: str = ""
    # "expense" | "income"；无法判定时留空交由上层按账户类型推断
    direction: str | None = None

    # ---- 质量与可追溯性 ----
    confidence: float = 0.0
    # 该行在原图中的位置 (x, y, w, h)，供待确认区高亮核对
    bbox: tuple[int, int, int, int] | None = None
    # 日期由「向上继承」或年份推断得出（附录 A.3.1 / A.3.2），UI 需标注提醒
    date_inferred: bool = False

    # ---- 排除标记（附录 A.2）----
    # 例：PayPay 的「支払い失敗」、信用卡账单页的「ご請求内訳」汇总行。
    # 这类行不静默丢弃，而是带原因传给上层，在待确认区告知用户已跳过。
    excluded: bool = False
    exclude_reason: str = ""

    # ---- 附加信息 ----
    # 交易后残高（三井住友銀行等逐行提供），可用于逐行对账（附录 A.3.6）
    balance_after: int | None = None
    # 分期信息，如 {"total_times": 48, "current_time": 17, "total_amount": 41487}
    installment: dict | None = None
    # 原始文本行，便于排查识别问题
    raw_text: str = ""


@dataclass
class ExtractResult:
    """一张截图的识别结果。"""

    transactions: list[RawTransaction] = field(default_factory=list)
    # 识别出的来源机构标识，如 "smbc_olive" / "smbc_bank" / "rakuten_card"
    # / "jwest_card" / "paypay"；未识别出为 None，走通用解析器
    detected_institution: str | None = None
    # 页面上的账户总残高（如三井住友銀行顶部的「預金残高」）
    detected_balance: int | None = None
    # 页面上的支払月锚点，用于无年份日期的年份推断（附录 A.3.2）
    statement_month: str | None = None  # "2026-08"
    # 非致命问题，展示在待确认区顶部
    warnings: list[str] = field(default_factory=list)
    # 使用的 Provider 标识，写入 import_images.ocr_provider
    provider: str = "none"
    # 原始识别输出，落库备查
    raw: dict | None = None


class ScreenshotExtractor(Protocol):
    """截图 → 原始交易列表。"""

    name: str

    def is_available(self) -> tuple[bool, str]:
        """是否已配置可用。返回 (可用, 不可用时的原因说明)。"""
        ...

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:
        ...


class ExtractorNotConfigured(RuntimeError):
    """Provider 未配置或依赖缺失时抛出，由 API 层转为对用户可读的提示。"""
