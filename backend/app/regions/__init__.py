"""地区包（需求书 D9）。

同一套核心（判重、分类判别链、预算、报表、合规模式）服务不同国家的账本，
随地区变化的只有这几样：

- **币种与最小单位**：金额全链路是「最小货币单位」的整数——日元存円（0 位小数），
  人民币存分（2 位小数）。数据库、API 里永远是整数，只有显示与输入时按位数换算
- **默认时区**：「今天」按用户所在地区算
- **预置类目、商家词典**：分别在 `services/seed.py` 与 `services/categorize/dictionary.py`
  里按地区键取（日本的原地不动，其他地区放在本包的子模块里）
- **按金额量级定的常量**：合规模式的月均支出保底、建议预算的取整步长

地区在建用户时选定、之后不可改：同一个整数在两种币种下是两种金额，改了等于把旧账全部换算错。
新增一个地区 = 在 REGIONS 里加一项 + 一棵类目树 + 一份商家词典。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    key: str
    currency: str  # ISO 4217
    # 金额存储的小数位：存的整数 = 金额 × 10^minor_unit
    minor_unit: int
    timezone: str
    default_locale: str
    # 合规模式：月均支出的保底值（最小单位）。刚开始记账、月支出很小时，别让一点差额就拉满警报
    compliance_floor: int
    # 建议预算向上取整的步长（最小单位）：（单个类目, 总额）
    budget_step_category: int
    budget_step_total: int

    @property
    def scale(self) -> int:
        return 10**self.minor_unit


JP = Region(
    key="JP",
    currency="JPY",
    minor_unit=0,
    timezone="Asia/Tokyo",
    default_locale="ja",
    compliance_floor=50_000,  # 5 万円
    budget_step_category=1_000,
    budget_step_total=5_000,
)

CN = Region(
    key="CN",
    currency="CNY",
    minor_unit=2,
    timezone="Asia/Shanghai",
    default_locale="zh-CN",
    compliance_floor=300_000,  # 3,000 元
    budget_step_category=5_000,  # 50 元
    budget_step_total=20_000,  # 200 元
)

REGIONS: dict[str, Region] = {r.key: r for r in (CN, JP)}
DEFAULT_REGION = JP


def get_region(key: str | None) -> Region:
    """未知或为空的键退回日本——升级前建的用户都是日元账本。"""
    return REGIONS.get((key or "").upper(), DEFAULT_REGION)


def region_of(user) -> Region:
    return get_region(getattr(user, "region", None))
