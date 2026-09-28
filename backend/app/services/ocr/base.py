from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawTransaction:
    date: dt.date | None = None
    time: dt.time | None = None
    amount: int | None = None
    merchant_raw: str = ""
    direction: str | None = None

    confidence: float = 0.0
    bbox: tuple[int, int, int, int] | None = None
    date_inferred: bool = False

    excluded: bool = False
    exclude_reason: str = ""

    balance_after: int | None = None
    installment: dict | None = None
    raw_text: str = ""


@dataclass
class ExtractResult:
    transactions: list[RawTransaction] = field(default_factory=list)
    detected_institution: str | None = None
    detected_balance: int | None = None
    statement_month: str | None = None  # "2026-08"
    warnings: list[str] = field(default_factory=list)
    provider: str = "none"
    raw: dict | None = None


class ScreenshotExtractor(Protocol):
    name: str

    def is_available(self) -> tuple[bool, str]:
        ...

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:
        ...


class ExtractorNotConfigured(RuntimeError):
    ...
