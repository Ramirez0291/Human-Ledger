from __future__ import annotations

import enum


class AccountType(str, enum.Enum):
    cash = "cash"
    bank = "bank"
    credit_card = "credit_card"
    emoney = "emoney"
    prepaid = "prepaid"
    investment = "investment"


class Direction(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer_out = "transfer_out"
    transfer_in = "transfer_in"


class CategoryType(str, enum.Enum):
    expense = "expense"
    income = "income"


class TxnSource(str, enum.Enum):
    manual = "manual"
    screenshot = "screenshot"
    csv = "csv"
    recurring = "recurring"


class BatchStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    discarded = "discarded"
    reverted = "reverted"


class DupStatus(str, enum.Enum):
    none = "none"
    merged = "merged"
    duplicate = "duplicate"
    maybe = "maybe"


class CategorySource(str, enum.Enum):
    rule = "rule"
    memory = "memory"
    dictionary = "dictionary"
    llm = "llm"
    none = "none"


class MatchType(str, enum.Enum):
    exact = "exact"
    contains = "contains"
    regex = "regex"


class RecurringFreq(str, enum.Enum):
    monthly = "monthly"
    bimonthly = "bimonthly"
    yearly = "yearly"


class RecurringMode(str, enum.Enum):
    auto = "auto"
    remind = "remind"


class SnapshotSource(str, enum.Enum):
    manual = "manual"
    ocr = "ocr"


class OcrProvider(str, enum.Enum):
    none = "none"
    local = "local"
    cloud_llm = "cloud_llm"
