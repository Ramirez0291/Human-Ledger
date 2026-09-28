"""Categorization chain: user rules -> merchant memory -> built-in dictionary."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import CategorySource, MatchType
from app.db.models import Category, CategoryRule, MerchantMemory
from app.services.categorize import dictionary
from app.services.normalize import merchant_brand, normalize_merchant


@dataclass
class Verdict:
    category_id: int | None
    confidence: float
    source: CategorySource
    transfer_hint: bool = False


class Categorizer:
    def __init__(self, db: Session, user_id: int) -> None:
        self.db = db
        self.user_id = user_id
        self._rules = self._load_rules()
        self._key_to_id = self._load_category_keys()
        self._memory_cache: dict[str, tuple[int, int]] = {}


    def _load_rules(self) -> list[tuple[CategoryRule, re.Pattern[str] | str]]:
        rows = (
            self.db.execute(
                select(CategoryRule)
                .where(CategoryRule.user_id == self.user_id, CategoryRule.enabled.is_(True))
                .order_by(CategoryRule.priority.desc(), CategoryRule.id)
            )
            .scalars()
            .all()
        )
        compiled: list[tuple[CategoryRule, re.Pattern[str] | str]] = []
        for rule in rows:
            if rule.match_type == MatchType.regex:
                try:
                    compiled.append((rule, re.compile(rule.pattern, re.IGNORECASE)))
                except re.error:
                    continue
            else:
                compiled.append((rule, normalize_merchant(rule.pattern)))
        return compiled

    def _load_category_keys(self) -> dict[str, int]:
        rows = self.db.execute(
            select(Category.key, Category.id, Category.type).where(Category.user_id == self.user_id)
        ).all()
        self._type_of: dict[int, str] = {i: t.value for _, i, t in rows}
        return {k: i for k, i, _ in rows}

    def _fits(self, category_id: int | None, direction: str | None) -> bool:
        if category_id is None or direction not in ("expense", "income"):
            return True
        return self._type_of.get(category_id, direction) == direction


    def _by_rule(self, merchant_norm: str, account_id: int | None) -> int | None:
        for rule, needle in self._rules:
            if rule.account_id is not None and rule.account_id != account_id:
                continue
            if isinstance(needle, re.Pattern):
                if needle.search(merchant_norm):
                    return rule.category_id
            elif rule.match_type == MatchType.exact:
                if merchant_norm == needle:
                    return rule.category_id
            elif needle and needle in merchant_norm:
                return rule.category_id
        return None

    def _by_memory(self, merchant_norm: str) -> tuple[int, float] | None:
        if merchant_norm in self._memory_cache:
            cid, hits = self._memory_cache[merchant_norm]
        else:
            row = self.db.execute(
                select(MerchantMemory.category_id, MerchantMemory.hit_count).where(
                    MerchantMemory.user_id == self.user_id,
                    MerchantMemory.merchant_norm == merchant_norm,
                )
            ).first()
            if row is None:
                return None
            cid, hits = int(row[0]), int(row[1])
            self._memory_cache[merchant_norm] = (cid, hits)
        return cid, min(0.95, 0.6 + 0.05 * hits)

    def _by_dictionary(
        self, merchant_norm: str, direction: str | None = None
    ) -> tuple[int | None, bool]:
        transfer = False
        cid: int | None = None
        saw_wrong_side = False
        for entry in dictionary.lookup_all(merchant_norm):
            transfer = transfer or entry.transfer
            if cid is not None or not entry.category_key:
                continue
            candidate = self._key_to_id.get(entry.category_key)
            if candidate is None:
                continue
            if self._fits(candidate, direction):
                cid = candidate
            else:
                saw_wrong_side = True
        if cid is None and saw_wrong_side and direction == "income":
            cid = self._key_to_id.get("income.refund")
        return cid, transfer


    def classify(
        self, merchant_raw: str, account_id: int | None = None, direction: str | None = None
    ) -> Verdict:
        norm = normalize_merchant(merchant_raw)
        if not norm:
            return Verdict(None, 0.0, CategorySource.none)

        dict_cid, transfer_hint = self._by_dictionary(norm, direction)

        cid = self._by_rule(norm, account_id)
        if cid is not None and self._fits(cid, direction):
            return Verdict(cid, 1.0, CategorySource.rule, transfer_hint)

        mem = self._by_memory(norm)
        if mem is None:
            brand = merchant_brand(merchant_raw)
            if brand and brand != norm:
                mem = self._by_memory(brand)
        if mem is not None and self._fits(mem[0], direction):
            return Verdict(mem[0], mem[1], CategorySource.memory, transfer_hint)

        if dict_cid is not None:
            return Verdict(dict_cid, 0.7, CategorySource.dictionary, transfer_hint)


        return Verdict(None, 0.0, CategorySource.none, transfer_hint)
