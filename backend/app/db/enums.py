"""领域枚举。

存储为 VARCHAR + CHECK 约束（native_enum=False），SQLite 与 Postgres 行为一致，
且迁移时无需处理数据库原生枚举类型的增删。
"""

from __future__ import annotations

import enum


class AccountType(str, enum.Enum):
    """账户类型。"""

    cash = "cash"  # 现金
    bank = "bank"  # 银行账户
    credit_card = "credit_card"  # 信用卡
    emoney = "emoney"  # 电子钱包（PayPay / 楽天ペイ / d払い 等）
    prepaid = "prepaid"  # 预付卡（Suica / ICOCA 等）
    investment = "investment"  # 证券 / 投资（楽天証券 等）：转进去的钱不是消费


class Direction(str, enum.Enum):
    """交易方向。

    转账拆为两条记录（transfer_out / transfer_in），共享 transfer_group_id，
    二者均不计入收支统计——否则 ATM 取现、信用卡还款会被双重计入。
    """

    expense = "expense"
    income = "income"
    transfer_out = "transfer_out"
    transfer_in = "transfer_in"


class CategoryType(str, enum.Enum):
    expense = "expense"
    income = "income"


class TxnSource(str, enum.Enum):
    """交易来源。"""

    manual = "manual"
    screenshot = "screenshot"
    csv = "csv"
    recurring = "recurring"


class BatchStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    discarded = "discarded"
    reverted = "reverted"  # 已确认后整批撤销：入账的交易进回收站


class DupStatus(str, enum.Enum):
    """待确认交易的判重状态（对应需求书 F4.2）。"""

    none = "none"  # 未发现重复
    merged = "merged"  # L1/L2：同图内或图间重叠，已合并，可展开还原
    duplicate = "duplicate"  # L3：与库内已有交易指纹相同，默认不勾选
    maybe = "maybe"  # L3b：模糊匹配命中，默认勾选但高亮


class CategorySource(str, enum.Enum):
    """分类判别链的命中层级（对应需求书 F5.2）。"""

    rule = "rule"  # 用户规则
    memory = "memory"  # 商家记忆
    dictionary = "dictionary"  # 内置日本商家词典
    llm = "llm"  # LLM 兜底
    none = "none"  # 未分类


class MatchType(str, enum.Enum):
    exact = "exact"
    contains = "contains"
    regex = "regex"


class RecurringFreq(str, enum.Enum):
    monthly = "monthly"
    bimonthly = "bimonthly"  # 每 2 个月（部分水道料金）
    yearly = "yearly"  # 年度（住民税、自動車税 等）


class RecurringMode(str, enum.Enum):
    auto = "auto"  # 到期自动生成账目
    remind = "remind"  # 仅提醒，用户确认后生成


class SnapshotSource(str, enum.Enum):
    manual = "manual"
    ocr = "ocr"


class OcrProvider(str, enum.Enum):
    none = "none"
    local = "local"
    cloud_llm = "cloud_llm"
