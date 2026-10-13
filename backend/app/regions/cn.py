"""中国地区包：预置类目与商家词典。

与日本版的差异：
- 外卖、奶茶、打车、共享单车是高频独立项；没有住民税 / 年金这类自己缴的税（工资里代扣）
- **人情往来**是一级类目：微信红包、转账给人在中国是日常收支的一大块，
  混进「其他」的话报表里会出现一个说不清的大窟窿
- 收入侧有「红包收入」「他人转账」，对应微信 / 支付宝里别人发来的钱
- 「手续费」单列：微信零钱提现的服务费、信用卡分期手续费

商家词典的模式与日本版同一套写法（contains 匹配规范化后的商家名，`re:` 开头为正则），
因此同样走 `dictionary._norm` 规范化。微信账单的交易对方多是品牌名（「麦当劳」「喜茶」），
比日本卡商明细干净得多，词典按品牌写即可。
"""

from __future__ import annotations

from app.services.categorize.dictionary import DictEntry
from app.services.seed import _c

EXPENSE_TREE = [
    _c("food", "🍚", "#E8663D", "餐饮", "食費", "Food & Dining", [
        _c("food.dining", "🍜", "#E8663D", "堂食", "外食", "Dining Out"),
        _c("food.delivery", "🛵", "#E8663D", "外卖", "デリバリー", "Food Delivery"),
        _c("food.groceries", "🥬", "#E8663D", "买菜", "食料品", "Groceries"),
        _c("food.cafe", "🧋", "#E8663D", "奶茶咖啡", "カフェ・ドリンク", "Drinks & Coffee"),
        _c("food.snacks", "🍎", "#E8663D", "零食水果", "お菓子・果物", "Snacks & Fruit"),
    ]),
    _c("shopping", "🛍️", "#3D8FE8", "购物", "買い物", "Shopping", [
        _c("shopping.online", "📦", "#3D8FE8", "网购", "ネット通販", "Online Shopping"),
        _c("shopping.supermarket", "🏪", "#3D8FE8", "超市便利店", "スーパー・コンビニ", "Supermarket & Convenience"),
        _c("shopping.daily", "🧻", "#3D8FE8", "日用品", "日用雑貨", "Household Supplies"),
        _c("shopping.digital", "💻", "#3D8FE8", "数码家电", "家電・デジタル", "Electronics"),
        _c("shopping.clothing", "👕", "#3D8FE8", "服饰鞋包", "衣類・バッグ", "Clothing"),
    ]),
    _c("transport", "🚇", "#10B981", "交通", "交通費", "Transport", [
        _c("transport.transit", "🚌", "#10B981", "地铁公交", "電車・バス", "Metro & Bus"),
        _c("transport.taxi", "🚕", "#10B981", "打车", "タクシー", "Taxi & Ride-hailing"),
        _c("transport.intercity", "🚄", "#10B981", "火车机票", "新幹線・飛行機", "Trains & Flights"),
        _c("transport.car", "⛽", "#10B981", "爱车养车", "車・バイク", "Car & Motorbike"),
        _c("transport.bike", "🚲", "#10B981", "共享单车", "シェアサイクル", "Bike Sharing"),
    ]),
    _c("housing", "🏠", "#8B5CF6", "居住", "住居", "Housing", [
        _c("housing.rent", "🔑", "#8B5CF6", "房租", "家賃", "Rent"),
        _c("housing.property", "🏢", "#8B5CF6", "物业费", "管理費", "Property Fee"),
        _c("housing.utilities", "💡", "#8B5CF6", "水电燃气", "水道光熱費", "Utilities"),
        _c("housing.repair", "🔧", "#8B5CF6", "维修家居", "修繕・インテリア", "Repairs & Furnishing"),
    ]),
    _c("comm", "📱", "#06B6D4", "通讯", "通信費", "Communication", [
        _c("comm.mobile", "📞", "#06B6D4", "话费", "携帯料金", "Mobile"),
        _c("comm.internet", "🌐", "#06B6D4", "宽带", "インターネット", "Internet"),
        _c("comm.subscription", "🔁", "#06B6D4", "会员订阅", "サブスク", "Memberships"),
    ]),
    _c("entertainment", "🎮", "#EC4899", "娱乐", "娯楽", "Entertainment", [
        _c("entertainment.games", "🎮", "#EC4899", "游戏", "ゲーム", "Games"),
        _c("entertainment.shows", "🎬", "#EC4899", "电影演出", "映画・ライブ", "Movies & Shows"),
        _c("entertainment.travel", "✈️", "#EC4899", "旅行", "旅行", "Travel"),
        _c("entertainment.hobby", "🎨", "#EC4899", "兴趣爱好", "趣味", "Hobbies"),
    ]),
    _c("medical", "🏥", "#EF4444", "医疗", "医療費", "Medical", [
        _c("medical.hospital", "🩺", "#EF4444", "看病", "診察", "Hospital"),
        _c("medical.medicine", "💊", "#EF4444", "药品", "薬", "Medicine"),
    ]),
    _c("education", "📚", "#6366F1", "学习", "教育・自己投資", "Education", [
        _c("education.tuition", "🎓", "#6366F1", "学费培训", "学費・講座", "Tuition & Courses"),
        _c("education.books", "📖", "#6366F1", "书籍", "書籍", "Books"),
    ]),
    _c("beauty", "💄", "#F472B6", "美容个护", "美容", "Beauty & Care", [
        _c("beauty.salon", "💇", "#F472B6", "美发", "美容院", "Hair Salon"),
        _c("beauty.cosmetics", "🧴", "#F472B6", "护肤化妆", "化粧品", "Cosmetics"),
    ]),
    # 微信红包、转账给人：中国日常收支的一大块，单列一级
    _c("social", "🧧", "#F97316", "人情往来", "交際・お付き合い", "Social & Gifts", [
        _c("social.redpacket", "🧧", "#F97316", "发红包", "お祝い・お年玉", "Red Packets Sent"),
        _c("social.transfer", "💸", "#F97316", "转账给人", "個人への送金", "Transfers to People"),
        _c("social.gift", "🎁", "#F97316", "礼物", "プレゼント", "Gifts"),
        _c("social.treat", "🍻", "#F97316", "请客聚餐", "飲み会・ごちそう", "Treats & Gatherings"),
    ]),
    _c("family", "👨‍👩‍👧", "#0EA5E9", "家庭", "家族", "Family", [
        _c("family.parents", "👴", "#0EA5E9", "孝敬父母", "親への仕送り", "Parents"),
        _c("family.kids", "🧒", "#0EA5E9", "子女", "子ども", "Children"),
        _c("family.pets", "🐱", "#0EA5E9", "宠物", "ペット", "Pets"),
    ]),
    _c("insurance", "🛡️", "#64748B", "保险", "保険", "Insurance", [
        _c("insurance.commercial", "📄", "#64748B", "商业保险", "民間保険", "Commercial Insurance"),
    ]),
    _c("finance", "🧾", "#78716C", "金融税费", "金融・税金", "Finance & Tax", [
        _c("finance.fee", "🧾", "#78716C", "手续费", "手数料", "Fees"),
        _c("finance.interest", "💳", "#78716C", "利息", "利息", "Interest"),
        # 工资里代扣的个税不经手；这里是个税年度汇算补税、个体户缴税等自己交的
        _c("finance.tax", "🏛️", "#78716C", "税费", "税金", "Taxes"),
    ]),
    _c("other", "📦", "#9CA3AF", "其他", "その他", "Other", [
        _c("other.uncategorized", "❓", "#9CA3AF", "未分类", "未分類", "Uncategorized"),
    ]),
]

INCOME_TREE = [
    _c("income", "💰", "#22C55E", "收入", "収入", "Income", [
        _c("income.salary", "💵", "#22C55E", "工资", "給与", "Salary"),
        _c("income.bonus", "🎉", "#22C55E", "奖金", "賞与", "Bonus"),
        _c("income.side_job", "💼", "#22C55E", "副业兼职", "副業", "Side Job"),
        _c("income.redpacket", "🧧", "#22C55E", "收红包", "お祝い・お年玉（受取）", "Red Packets Received"),
        _c("income.transfer", "💸", "#22C55E", "他人转账", "個人からの入金", "Transfers from People"),
        _c("income.investment", "📈", "#22C55E", "理财收益", "運用益", "Investment Returns"),
        _c("income.refund", "↩️", "#22C55E", "退款", "返金", "Refunds"),
        _c("income.other", "➕", "#22C55E", "其他收入", "その他収入", "Other Income"),
    ]),
]


# 顺序有意义：先匹配到的先生效，更具体的放前面
DICTIONARY: tuple[DictEntry, ...] = (
    # ---- 转账提示：钱只是换了个口袋，记成支出会双计 ----
    DictEntry("信用卡还款", None, transfer=True),
    DictEntry("还款", None, transfer=True),
    DictEntry("零钱充值", None, transfer=True),
    DictEntry("零钱提现", None, transfer=True),
    DictEntry("零钱通", None, transfer=True),
    DictEntry("余额宝", None, transfer=True),
    DictEntry("理财通", None, transfer=True),
    DictEntry("re:^(?:充值|提现)$", None, transfer=True),
    DictEntry("atm取款", None, transfer=True),
    DictEntry("取款", None, transfer=True),

    # ---- 外卖（放在餐饮品牌之前：「美团外卖」不该落到堂食）----
    DictEntry("美团外卖", "food.delivery"),
    DictEntry("饿了么", "food.delivery"),
    DictEntry("外卖", "food.delivery"),

    # ---- 奶茶咖啡 ----
    DictEntry("喜茶", "food.cafe"),
    DictEntry("奈雪", "food.cafe"),
    DictEntry("蜜雪冰城", "food.cafe"),
    DictEntry("茶百道", "food.cafe"),
    DictEntry("古茗", "food.cafe"),
    DictEntry("霸王茶姬", "food.cafe"),
    DictEntry("一点点", "food.cafe"),
    DictEntry("coco都可", "food.cafe"),
    DictEntry("沪上阿姨", "food.cafe"),
    DictEntry("书亦烧仙草", "food.cafe"),
    DictEntry("瑞幸", "food.cafe"),
    DictEntry("luckin", "food.cafe"),
    DictEntry("星巴克", "food.cafe"),
    DictEntry("starbucks", "food.cafe"),
    DictEntry("库迪", "food.cafe"),
    DictEntry("manner", "food.cafe"),
    DictEntry("tims", "food.cafe"),
    DictEntry("八马茶业", "food.cafe"),
    DictEntry("农夫山泉", "food.cafe"),  # 自动售货机的水和饮料
    DictEntry("咖啡", "food.cafe"),
    DictEntry("奶茶", "food.cafe"),
    DictEntry("茶饮", "food.cafe"),

    # ---- 堂食 / 快餐 ----
    DictEntry("麦当劳", "food.dining"),
    DictEntry("金拱门", "food.dining"),
    DictEntry("肯德基", "food.dining"),
    DictEntry("kfc", "food.dining"),
    DictEntry("汉堡王", "food.dining"),
    DictEntry("塔斯汀", "food.dining"),
    DictEntry("华莱士", "food.dining"),
    DictEntry("必胜客", "food.dining"),
    DictEntry("达美乐", "food.dining"),
    DictEntry("萨莉亚", "food.dining"),
    DictEntry("海底捞", "food.dining"),
    DictEntry("西贝", "food.dining"),
    DictEntry("老乡鸡", "food.dining"),
    DictEntry("真功夫", "food.dining"),
    DictEntry("吉野家", "food.dining"),
    DictEntry("味千", "food.dining"),
    DictEntry("太二", "food.dining"),
    DictEntry("绝味", "food.snacks"),
    DictEntry("周黑鸭", "food.snacks"),
    DictEntry("良品铺子", "food.snacks"),
    DictEntry("三只松鼠", "food.snacks"),
    DictEntry("百果园", "food.snacks"),
    DictEntry("水果", "food.snacks"),
    DictEntry("糖水", "food.snacks"),
    DictEntry("甜品", "food.snacks"),
    DictEntry("面包", "food.snacks"),
    DictEntry("烘焙", "food.snacks"),
    DictEntry("餐厅", "food.dining"),
    DictEntry("饭店", "food.dining"),
    DictEntry("餐饮", "food.dining"),
    DictEntry("火锅", "food.dining"),
    DictEntry("烧烤", "food.dining"),
    DictEntry("面馆", "food.dining"),
    DictEntry("粉面", "food.dining"),
    DictEntry("生煎", "food.dining"),
    DictEntry("小吃", "food.dining"),
    DictEntry("食堂", "food.dining"),
    DictEntry("快餐", "food.dining"),

    # ---- 买菜 / 超市便利店 ----
    DictEntry("盒马", "food.groceries"),
    DictEntry("叮咚买菜", "food.groceries"),
    DictEntry("朴朴", "food.groceries"),
    DictEntry("美团买菜", "food.groceries"),
    DictEntry("小象超市", "food.groceries"),
    DictEntry("钱大妈", "food.groceries"),
    DictEntry("菜市场", "food.groceries"),
    DictEntry("生鲜", "food.groceries"),
    DictEntry("沃尔玛", "shopping.supermarket"),
    DictEntry("山姆", "shopping.supermarket"),
    DictEntry("永辉", "shopping.supermarket"),
    DictEntry("大润发", "shopping.supermarket"),
    DictEntry("华润万家", "shopping.supermarket"),
    DictEntry("物美", "shopping.supermarket"),
    DictEntry("家乐福", "shopping.supermarket"),
    DictEntry("costco", "shopping.supermarket"),
    DictEntry("开市客", "shopping.supermarket"),
    DictEntry("7-eleven", "shopping.supermarket"),
    DictEntry("eleven", "shopping.supermarket"),  # 「广东 ELEVEN 7」
    DictEntry("7-11", "shopping.supermarket"),
    DictEntry("全家", "shopping.supermarket"),
    DictEntry("罗森", "shopping.supermarket"),
    DictEntry("美宜佳", "shopping.supermarket"),
    DictEntry("便利蜂", "shopping.supermarket"),
    DictEntry("天福", "shopping.supermarket"),
    DictEntry("便利店", "shopping.supermarket"),
    DictEntry("士多", "shopping.supermarket"),
    DictEntry("超市", "shopping.supermarket"),

    # ---- 网购 / 购物 ----
    DictEntry("拼多多", "shopping.online"),
    DictEntry("淘宝", "shopping.online"),
    DictEntry("天猫", "shopping.online"),
    DictEntry("京东", "shopping.online"),
    DictEntry("唯品会", "shopping.online"),
    DictEntry("得物", "shopping.online"),
    DictEntry("抖音电商", "shopping.online"),
    DictEntry("抖音商城", "shopping.online"),
    DictEntry("闲鱼", "shopping.online"),
    DictEntry("苏宁", "shopping.digital"),
    DictEntry("国美", "shopping.digital"),
    DictEntry("apple", "shopping.digital"),
    DictEntry("小米", "shopping.digital"),
    DictEntry("华为", "shopping.digital"),
    DictEntry("名创优品", "shopping.daily"),
    DictEntry("无印良品", "shopping.daily"),
    DictEntry("muji", "shopping.daily"),
    DictEntry("泡泡玛特", "entertainment.hobby"),
    DictEntry("popmart", "entertainment.hobby"),
    DictEntry("屈臣氏", "beauty.cosmetics"),
    DictEntry("优衣库", "shopping.clothing"),
    DictEntry("uniqlo", "shopping.clothing"),
    DictEntry("zara", "shopping.clothing"),
    DictEntry("h&m", "shopping.clothing"),
    DictEntry("安踏", "shopping.clothing"),
    DictEntry("李宁", "shopping.clothing"),
    DictEntry("耐克", "shopping.clothing"),
    DictEntry("nike", "shopping.clothing"),
    DictEntry("顺丰", "shopping.daily"),  # 寄快递
    DictEntry("中通快递", "shopping.daily"),
    DictEntry("圆通", "shopping.daily"),
    DictEntry("韵达", "shopping.daily"),
    DictEntry("快递", "shopping.daily"),
    DictEntry("宜家", "housing.repair"),
    DictEntry("ikea", "housing.repair"),

    # ---- 交通 ----
    DictEntry("12306", "transport.intercity"),
    DictEntry("中铁网络", "transport.intercity"),
    DictEntry("铁路", "transport.intercity"),
    DictEntry("携程", "entertainment.travel"),
    DictEntry("去哪儿", "entertainment.travel"),
    DictEntry("飞猪", "entertainment.travel"),
    DictEntry("同程", "entertainment.travel"),
    DictEntry("航空", "transport.intercity"),
    DictEntry("机票", "transport.intercity"),
    DictEntry("机场", "transport.intercity"),
    DictEntry("空港", "transport.intercity"),  # 「関西国際空港」：出境旅行的境外消费也会出现在微信账单里
    DictEntry("airlines", "transport.intercity"),
    DictEntry("airways", "transport.intercity"),
    DictEntry("cathay", "transport.intercity"),
    DictEntry("滴滴", "transport.taxi"),
    DictEntry("高德打车", "transport.taxi"),
    DictEntry("曹操出行", "transport.taxi"),
    DictEntry("t3出行", "transport.taxi"),
    DictEntry("如祺出行", "transport.taxi"),
    DictEntry("花小猪", "transport.taxi"),
    DictEntry("出租车", "transport.taxi"),
    DictEntry("打车", "transport.taxi"),
    DictEntry("哈啰", "transport.bike"),
    DictEntry("青桔", "transport.bike"),
    DictEntry("美团单车", "transport.bike"),
    DictEntry("单车", "transport.bike"),
    DictEntry("地铁", "transport.transit"),
    DictEntry("公交", "transport.transit"),
    DictEntry("轨道交通", "transport.transit"),
    DictEntry("乘车码", "transport.transit"),
    DictEntry("深圳通", "transport.transit"),
    DictEntry("羊城通", "transport.transit"),
    DictEntry("交通卡", "transport.transit"),
    DictEntry("中石化", "transport.car"),
    DictEntry("中石油", "transport.car"),
    DictEntry("加油", "transport.car"),
    DictEntry("停车", "transport.car"),
    DictEntry("re:^etc", "transport.car"),
    DictEntry("高速", "transport.car"),
    DictEntry("充电宝", "shopping.daily"),  # 街电 / 怪兽充电 的租借，别落到车辆充电
    DictEntry("充电", "transport.car"),

    # ---- 通讯 / 订阅 ----
    DictEntry("手机充值", "comm.mobile"),
    DictEntry("话费", "comm.mobile"),
    DictEntry("中国移动", "comm.mobile"),
    DictEntry("中国联通", "comm.mobile"),
    DictEntry("中国电信", "comm.mobile"),
    DictEntry("联通", "comm.mobile"),  # 「广东联通」
    DictEntry("电信", "comm.mobile"),
    DictEntry("宽带", "comm.internet"),
    DictEntry("腾讯视频", "comm.subscription"),
    DictEntry("爱奇艺", "comm.subscription"),
    DictEntry("优酷", "comm.subscription"),
    DictEntry("芒果tv", "comm.subscription"),
    DictEntry("哔哩哔哩", "comm.subscription"),
    DictEntry("bilibili", "comm.subscription"),
    DictEntry("网易云音乐", "comm.subscription"),
    DictEntry("qq音乐", "comm.subscription"),
    DictEntry("百度网盘", "comm.subscription"),
    DictEntry("会员", "comm.subscription"),

    # ---- 居住 ----
    DictEntry("电费", "housing.utilities"),
    DictEntry("水费", "housing.utilities"),
    DictEntry("燃气", "housing.utilities"),
    DictEntry("供电", "housing.utilities"),
    DictEntry("电网", "housing.utilities"),
    DictEntry("自来水", "housing.utilities"),
    DictEntry("物业", "housing.property"),
    DictEntry("房租", "housing.rent"),
    DictEntry("租金", "housing.rent"),
    DictEntry("自如", "housing.rent"),

    # ---- 娱乐 ----
    DictEntry("腾讯游戏", "entertainment.games"),
    DictEntry("网易游戏", "entertainment.games"),
    DictEntry("米哈游", "entertainment.games"),
    DictEntry("鹰角", "entertainment.games"),
    DictEntry("塔罗斯", "entertainment.games"),  # 鹰角网络（明日方舟）
    DictEntry("叠纸", "entertainment.games"),
    DictEntry("steam", "entertainment.games"),
    DictEntry("游戏", "entertainment.games"),
    DictEntry("猫眼", "entertainment.shows"),
    DictEntry("淘票票", "entertainment.shows"),
    DictEntry("大麦", "entertainment.shows"),
    DictEntry("电影", "entertainment.shows"),
    DictEntry("影城", "entertainment.shows"),
    DictEntry("酒店", "entertainment.travel"),
    DictEntry("宾馆", "entertainment.travel"),
    DictEntry("景区", "entertainment.travel"),
    DictEntry("门票", "entertainment.travel"),

    # ---- 医疗 / 学习 / 美容 ----
    DictEntry("医院", "medical.hospital"),
    DictEntry("诊所", "medical.hospital"),
    DictEntry("门诊", "medical.hospital"),
    DictEntry("药房", "medical.medicine"),
    DictEntry("药店", "medical.medicine"),
    DictEntry("大药房", "medical.medicine"),
    DictEntry("书店", "education.books"),
    DictEntry("当当", "education.books"),
    DictEntry("培训", "education.tuition"),
    DictEntry("学费", "education.tuition"),
    DictEntry("理发", "beauty.salon"),
    DictEntry("美发", "beauty.salon"),

    # ---- 金融费用 ----
    DictEntry("服务费", "finance.fee"),
    DictEntry("手续费", "finance.fee"),
    DictEntry("利息", "finance.interest"),
    DictEntry("税务", "finance.tax"),
    DictEntry("缴税", "finance.tax"),

    # ---- 兜底的平台名：放最后，让「美团买菜」「美团单车」先命中更具体的条目 ----
    DictEntry("美团", "food.delivery"),
    DictEntry("大众点评", "food.dining"),
)
