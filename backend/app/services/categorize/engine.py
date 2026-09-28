"""分类判别链（需求书 F5.2）。

按优先级依次尝试，返回 (category_id, 置信度, 命中层级, 转账提示)：

    1. 用户规则     exact / contains / regex，可限定账户        置信度 1.0
    2. 商家记忆     该 merchant_norm 历史上被归到哪类            0.6 + 0.05×命中次数，封顶 0.95
    3. 内置词典     常见日本商家                                  0.7
    4. LLM 兜底     （M2 云端 Provider 接入后启用）               0.6
    5. 未分类                                                     0.0

转账提示单独返回：即使某层给出了类别，词典若认为它像转账（信用卡还款、
IC 充值、ATM），也一并告知，待确认区据此提示用户指定对方账户。
"""

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
    """一次导入共用一个实例：规则与类目索引只加载一次。"""

    def __init__(self, db: Session, user_id: int) -> None:
        self.db = db
        self.user_id = user_id
        self._rules = self._load_rules()
        self._key_to_id = self._load_category_keys()
        self._memory_cache: dict[str, tuple[int, int]] = {}

    # ---- 加载 ----

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
                    continue  # 坏正则跳过，不让一条规则拖垮整批导入
            else:
                # exact / contains 与 merchant_norm 比对，模式也要走同一套规范化
                compiled.append((rule, normalize_merchant(rule.pattern)))
        return compiled

    def _load_category_keys(self) -> dict[str, int]:
        rows = self.db.execute(
            select(Category.key, Category.id, Category.type).where(Category.user_id == self.user_id)
        ).all()
        self._type_of: dict[int, str] = {i: t.value for _, i, t in rows}
        return {k: i for k, i, _ in rows}

    def _fits(self, category_id: int | None, direction: str | None) -> bool:
        """支出行不能落到收入类目，反之亦然。

        银行明细里「振込 ｺｸﾎｶﾝﾌﾟ」是国保退款（收入），词典按「コクホ」会给出
        税金类目——方向不符时这一层视为未命中，让后面的层或用户来定。
        """
        if category_id is None or direction not in ("expense", "income"):
            return True
        return self._type_of.get(category_id, direction) == direction

    # ---- 各层 ----

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
        """返回 (第一个方向相符的类目, 是否转账提示)。

        转账提示看的是任意命中条目；类目则跳过方向不符的条目继续往后找。
        收入行只命中了支出类商家（「AMAZON.CO.JP」的退款）时，退而归入「退款」。
        """
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

    # ---- 入口 ----

    def classify(
        self, merchant_raw: str, account_id: int | None = None, direction: str | None = None
    ) -> Verdict:
        norm = normalize_merchant(merchant_raw)
        if not norm:
            return Verdict(None, 0.0, CategorySource.none)

        # 转账提示独立于分类结果：先问词典
        dict_cid, transfer_hint = self._by_dictionary(norm, direction)

        cid = self._by_rule(norm, account_id)
        if cid is not None and self._fits(cid, direction):
            return Verdict(cid, 1.0, CategorySource.rule, transfer_hint)

        mem = self._by_memory(norm)
        if mem is None:
            # 精确键没记过：退回品牌键（PayPay「ブランド - 店舗名」的分店差异）
            brand = merchant_brand(merchant_raw)
            if brand and brand != norm:
                mem = self._by_memory(brand)
        if mem is not None and self._fits(mem[0], direction):
            return Verdict(mem[0], mem[1], CategorySource.memory, transfer_hint)

        if dict_cid is not None:
            return Verdict(dict_cid, 0.7, CategorySource.dictionary, transfer_hint)

        # 第 4 层 LLM 兜底：M2 云端 Provider 接入后在此调用

        return Verdict(None, 0.0, CategorySource.none, transfer_hint)
