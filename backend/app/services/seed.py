"""Default categories. Names live in category_names, one row per locale."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.enums import CategoryType
from app.db.models import Category, CategoryName

SUPPORTED_LOCALES: tuple[str, ...] = ("zh-CN", "ja", "en")


@dataclass(frozen=True)
class SeedCategory:
    key: str
    icon: str
    color: str
    names: dict[str, str]
    children: list["SeedCategory"] = field(default_factory=list)


def _c(key: str, icon: str, color: str, zh: str, ja: str, en: str, children=()) -> SeedCategory:
    return SeedCategory(
        key=key,
        icon=icon,
        color=color,
        names={"zh-CN": zh, "ja": ja, "en": en},
        children=list(children),
    )


EXPENSE_TREE: list[SeedCategory] = [
    _c("food", "🍚", "#E8663D", "餐饮食品", "食費", "Food & Dining", [
        _c("food.groceries", "🛒", "#E8663D", "食材杂货", "食料品", "Groceries"),
        _c("food.dining", "🍜", "#E8663D", "外食", "外食", "Dining Out"),
        _c("food.cafe", "☕", "#E8663D", "咖啡饮品", "カフェ", "Cafe"),
        _c("food.convenience", "🏪", "#E8663D", "便利店", "コンビニ", "Convenience Store"),
    ]),
    _c("daily", "🧺", "#3D8FE8", "日用品", "日用品", "Daily Goods", [
        _c("daily.supplies", "🧻", "#3D8FE8", "日用杂货", "日用雑貨", "Household Supplies"),
        _c("daily.furniture", "🛋️", "#3D8FE8", "家具家电", "家具・家電", "Furniture & Appliances"),
    ]),
    _c("housing", "🏠", "#8B5CF6", "居住", "住居", "Housing", [
        _c("housing.rent", "🔑", "#8B5CF6", "房租", "家賃", "Rent"),
        _c("housing.management", "🏢", "#8B5CF6", "管理费", "管理費", "Management Fee"),
        _c("housing.renewal", "📄", "#8B5CF6", "续约金", "更新料", "Renewal Fee"),
        _c("housing.fire_insurance", "🔥", "#8B5CF6", "火灾保险", "火災保険", "Fire Insurance"),
    ]),
    _c("utilities", "💡", "#F59E0B", "水电燃气", "水道光熱費", "Utilities", [
        _c("utilities.electricity", "⚡", "#F59E0B", "电费", "電気", "Electricity"),
        _c("utilities.gas", "🔥", "#F59E0B", "燃气费", "ガス", "Gas"),
        _c("utilities.water", "💧", "#F59E0B", "水费", "水道", "Water"),
    ]),
    _c("comm", "📱", "#06B6D4", "通信", "通信費", "Communication", [
        _c("comm.mobile", "📞", "#06B6D4", "手机", "携帯", "Mobile"),
        _c("comm.internet", "🌐", "#06B6D4", "网络", "インターネット", "Internet"),
        _c("comm.subscription", "🔁", "#06B6D4", "订阅服务", "サブスク", "Subscriptions"),
    ]),
    _c("transport", "🚃", "#10B981", "交通", "交通費", "Transport", [
        _c("transport.train_bus", "🚌", "#10B981", "电车巴士", "電車・バス", "Train & Bus"),
        _c("transport.ic_charge", "💳", "#10B981", "交通IC充值", "ICチャージ", "IC Card Top-up"),
        _c("transport.taxi", "🚕", "#10B981", "出租车", "タクシー", "Taxi"),
        _c("transport.fuel", "⛽", "#10B981", "汽油", "ガソリン", "Fuel"),
        _c("transport.highway", "🛣️", "#10B981", "高速费", "高速道路・ETC", "Highway & ETC"),
    ]),
    _c("medical", "🏥", "#EF4444", "医疗", "医療費", "Medical", [
        _c("medical.consultation", "🩺", "#EF4444", "就诊", "診察", "Consultation"),
        _c("medical.medicine", "💊", "#EF4444", "药品", "薬", "Medicine"),
        _c("medical.checkup", "📋", "#EF4444", "体检", "健康診断", "Health Checkup"),
    ]),
    _c("education", "📚", "#6366F1", "教育与自我投资", "教育・自己投資", "Education", [
        _c("education.tuition", "🎓", "#6366F1", "学费", "学費", "Tuition"),
        _c("education.books", "📖", "#6366F1", "书籍", "書籍", "Books"),
        _c("education.language", "🗣️", "#6366F1", "语言学习", "語学", "Language Study"),
    ]),
    _c("entertainment", "🎮", "#EC4899", "娱乐", "娯楽", "Entertainment", [
        _c("entertainment.travel", "✈️", "#EC4899", "旅行", "旅行", "Travel"),
        _c("entertainment.hobby", "🎨", "#EC4899", "兴趣爱好", "趣味", "Hobbies"),
        _c("entertainment.streaming", "📺", "#EC4899", "影音订阅", "動画配信", "Streaming"),
    ]),
    _c("beauty", "👕", "#F472B6", "服饰美容", "衣服・美容", "Clothing & Beauty", [
        _c("beauty.clothing", "👔", "#F472B6", "服装", "衣類", "Clothing"),
        _c("beauty.salon", "💇", "#F472B6", "美发", "美容院", "Hair Salon"),
        _c("beauty.cosmetics", "💄", "#F472B6", "化妆品", "化粧品", "Cosmetics"),
    ]),
    _c("social", "🎁", "#F97316", "人情交际", "交際費", "Social", [
        _c("social.gathering", "🍻", "#F97316", "聚餐", "飲み会", "Gatherings"),
        _c("social.gift", "🎀", "#F97316", "礼物", "プレゼント", "Gifts"),
    ]),
    _c("insurance", "🛡️", "#64748B", "保险", "保険", "Insurance", [
        _c("insurance.life", "❤️", "#64748B", "人寿保险", "生命保険", "Life Insurance"),
        _c("insurance.medical", "🏥", "#64748B", "医疗保险", "医療保険", "Medical Insurance"),
    ]),
    _c("tax", "🏛️", "#78716C", "税金与社保", "税金・社会保険", "Tax & Social Insurance", [
        _c("tax.resident", "🏘️", "#78716C", "住民税", "住民税", "Resident Tax"),
        _c("tax.income", "💴", "#78716C", "所得税", "所得税", "Income Tax"),
        _c("tax.pension", "👴", "#78716C", "年金", "年金", "Pension"),
        _c("tax.health_insurance", "🩹", "#78716C", "健康保险", "健康保険", "Health Insurance"),
        _c("tax.nursing_insurance", "🧑‍⚕️", "#78716C", "介护保险", "介護保険", "Nursing Care Insurance"),
    ]),
    _c("remittance", "🌏", "#0EA5E9", "汇款", "送金・仕送り", "Remittance", [
        _c("remittance.overseas", "💱", "#0EA5E9", "海外汇款", "海外送金", "Overseas Transfer"),
        _c("remittance.family", "👨‍👩‍👧", "#0EA5E9", "家用汇款", "家族仕送り", "Family Support"),
        _c("remittance.fee", "🧾", "#0EA5E9", "汇款手续费", "送金手数料", "Transfer Fee"),
    ]),
    _c("other", "📦", "#9CA3AF", "其他", "その他", "Other", [
        _c("other.uncategorized", "❓", "#9CA3AF", "未分类", "未分類", "Uncategorized"),
    ]),
]

INCOME_TREE: list[SeedCategory] = [
    _c("income", "💰", "#22C55E", "收入", "収入", "Income", [
        _c("income.salary", "💵", "#22C55E", "工资", "給与", "Salary"),
        _c("income.bonus", "🎉", "#22C55E", "奖金", "賞与", "Bonus"),
        _c("income.side_job", "💼", "#22C55E", "副业", "副業", "Side Job"),
        _c("income.refund", "↩️", "#22C55E", "退税返还", "還付金", "Refund"),
        _c("income.other", "➕", "#22C55E", "其他收入", "その他収入", "Other Income"),
    ]),
]


def _insert(
    db: Session,
    user_id: int,
    node: SeedCategory,
    ctype: CategoryType,
    parent_id: int | None,
    order: int,
) -> None:
    category = Category(
        user_id=user_id,
        parent_id=parent_id,
        key=node.key,
        type=ctype,
        icon=node.icon,
        color=node.color,
        is_system=True,
        sort_order=order,
    )
    db.add(category)
    db.flush()

    for locale in SUPPORTED_LOCALES:
        db.add(
            CategoryName(
                category_id=category.id,
                locale=locale,
                name=node.names[locale],
            )
        )

    for child_order, child in enumerate(node.children):
        _insert(db, user_id, child, ctype, category.id, child_order)


def seed_categories(db: Session, user_id: int) -> int:
    count_before = db.query(Category).filter(Category.user_id == user_id).count()
    if count_before:
        return 0

    for order, node in enumerate(EXPENSE_TREE):
        _insert(db, user_id, node, CategoryType.expense, None, order)
    for order, node in enumerate(INCOME_TREE):
        _insert(db, user_id, node, CategoryType.income, None, len(EXPENSE_TREE) + order)

    db.flush()
    return db.query(Category).filter(Category.user_id == user_id).count()
