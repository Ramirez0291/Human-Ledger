"""内置日本商家词典——分类判别链第 3 层（需求书 F5.2）。

模式与规范化后的商家名（merchant_norm：NFKC、小写、去空格）做 contains 匹配，
因此这里的模式也要写成规范化后的形式：全部小写、无空格、半角。

另含「转账提示」：信用卡还款、IC 卡充值、ATM 取现等匹配到时，标记为疑似转账，
待确认区会提示用户指定对方账户（附录 A.5.2）。不标记的话，
信用卡还款会与刷卡消费双重计入支出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DictEntry:
    pattern: str  # 规范化形式的子串，或以 "re:" 开头的正则
    category_key: str | None  # None 表示仅作转账提示
    transfer: bool = False


# 顺序有意义：先匹配到的先生效，因此更具体的模式放前面
ENTRIES: tuple[DictEntry, ...] = (
    # ---- 转账提示（优先于分类）----
    DictEntry("カードサービス", None, transfer=True),  # ラクテンカードサービス 等信用卡还款
    DictEntry("カード引落", None, transfer=True),
    DictEntry("カード代金", None, transfer=True),
    DictEntry("re:(?:jcb|visa|master|amex|ニコス|セゾン|エポス|イオンクレジット|三井住友カード|smbc|dc|uc|オリコ|jaccs)(?:カード)?(?:サービス|引落|代金|ご利用代金)", None, transfer=True),
    # 三井住友銀行口座明細：ATM 取现 / 存入写作「カード ｾﾌﾞﾝXX1234」「カード (123)」
    DictEntry("re:^カード", None, transfer=True),
    DictEntry("ミツイスミトモカード", None, transfer=True),  # 三井住友カード 还款
    DictEntry("三井住友カード", None, transfer=True),
    DictEntry("re:(?:ufj)?j-?west", None, transfer=True),  # J-WEST カード 还款（经 UFJ NICOS）
    DictEntry("チャージ", None, transfer=True),  # ICOCA / Suica / PayPay チャージ
    # 口座明細里的电子钱包充值只写钱包名（「ﾍﾟｲﾍﾟｲ」「ﾗｲﾝ ﾍﾟｲ」），也是转账
    DictEntry("ペイペイ", None, transfer=True),
    DictEntry("paypay", None, transfer=True),
    DictEntry("ラインペイ", None, transfer=True),
    DictEntry("linepay", None, transfer=True),
    DictEntry("オートチャージ", None, transfer=True),
    DictEntry("atm", None, transfer=True),
    DictEntry("カード出金", None, transfer=True),
    DictEntry("引き出し", None, transfer=True),
    DictEntry("振替", None, transfer=True),
    DictEntry("re:証券|シヨウケン", None, transfer=True),  # 转入证券账户是投资，不是消费
    # Paidy（あと払い）的月度扣款：钱付给的是 Paidy 这条信用线，实际消费在别处
    DictEntry("ペイデイ", None, transfer=True),
    DictEntry("paidy", None, transfer=True),
    # 银行明细的「Vｻｶﾞｸ123456」：iD 差额调整，金额小、方向不定，按转账提示让用户看一眼
    DictEntry("re:^vサガク", None, transfer=True),

    # ---- 常见连锁与服务（三井住友 / 楽天 / PayPay 明细中的写法）----
    DictEntry("ケンタッキー", "food.dining"),
    DictEntry("kfc", "food.dining"),
    DictEntry("バーガーキング", "food.dining"),
    DictEntry("ゼッテリア", "food.dining"),
    DictEntry("やよい軒", "food.dining"),
    DictEntry("一蘭", "food.dining"),
    DictEntry("天丼てんや", "food.dining"),
    DictEntry("焼肉ライク", "food.dining"),
    DictEntry("焼肉きんぐ", "food.dining"),
    DictEntry("リンガーハット", "food.dining"),
    DictEntry("宮本むなし", "food.dining"),
    DictEntry("矢場とん", "food.dining"),
    DictEntry("551蓬莱", "food.dining"),
    DictEntry("オリジン弁当", "food.dining"),
    DictEntry("キッチンオリジン", "food.dining"),
    DictEntry("自販機", "food.convenience"),
    DictEntry("newdays", "food.convenience"),
    DictEntry("カルディ", "food.groceries"),
    DictEntry("スーパー玉出", "food.groceries"),
    DictEntry("成城石井", "food.groceries"),
    DictEntry("星乃珈琲", "food.cafe"),
    DictEntry("星野珈琲", "food.cafe"),
    DictEntry("倉式珈琲", "food.cafe"),
    DictEntry("スマート珈琲", "food.cafe"),
    DictEntry("からふね屋", "food.cafe"),
    DictEntry("ホームセンター", "daily.supplies"),
    DictEntry("コーナン", "daily.supplies"),
    DictEntry("ハンズマン", "daily.supplies"),
    DictEntry("ハンズ", "daily.supplies"),
    DictEntry("ロフト", "daily.supplies"),
    DictEntry("loft", "daily.supplies"),
    DictEntry("日本郵便", "daily.supplies"),
    DictEntry("郵便局", "daily.supplies"),
    DictEntry("turbo通信料", "comm.internet"),
    DictEntry("通信料", "comm.internet"),
    DictEntry("nttファイナンス", "comm.internet"),
    DictEntry("nttフアイナンス", "comm.internet"),
    DictEntry("godaddy", "comm.subscription"),
    DictEntry("dmm", "entertainment.hobby"),
    DictEntry("シネマ", "entertainment.hobby"),
    DictEntry("シアター", "entertainment.hobby"),
    DictEntry("チケット", "entertainment.hobby"),
    DictEntry("宝くじ", "entertainment.hobby"),
    DictEntry("アニメイト", "entertainment.hobby"),
    DictEntry("expo", "entertainment.hobby"),
    DictEntry("公式オンラインストア", "entertainment.hobby"),
    DictEntry("楽器", "entertainment.hobby"),
    DictEntry("モバイルsuica", "transport.ic_charge"),
    DictEntry("モバイルicoca", "transport.ic_charge"),
    DictEntry("モバイルpasmo", "transport.ic_charge"),
    DictEntry("タイムズカー", "transport.fuel"),
    DictEntry("コインロッカー", "transport.train_bus"),
    DictEntry("空港", "entertainment.travel"),
    DictEntry("損害保険", "insurance"),
    DictEntry("損保", "insurance"),
    DictEntry("税務署", "tax.income"),
    DictEntry("ゼイムシヨ", "tax.income"),
    DictEntry("カンプ", "income.refund"),  # 還付（国保還付金 等）
    DictEntry("コクホ", "tax.health_insurance"),
    DictEntry("re:^pe[a-zA-Z0-9]*(?:オオサカシ|トウキヨウト|.*シヤクシヨ)", "tax.resident"),
    DictEntry("ドクターマーチン", "beauty.clothing"),
    DictEntry("靴下屋", "beauty.clothing"),
    DictEntry("アルペン", "beauty.clothing"),
    DictEntry("ナイキ", "beauty.clothing"),
    DictEntry("nike", "beauty.clothing"),
    DictEntry("送金手数料", "remittance.fee"),
    DictEntry("再発行手数料", "other"),
    DictEntry("re:^送金", "remittance.family"),
    DictEntry("re:^受取", "income.other"),
    DictEntry("ポイント獲得", "income.other"),
    DictEntry("ポイント期限切れ", "other"),
    DictEntry("ポイント、残高の取消", "other"),

    # ---- 食費 ----
    DictEntry("セブン-イレブン", "food.convenience"),
    DictEntry("セブンイレブン", "food.convenience"),
    DictEntry("ローソン", "food.convenience"),
    DictEntry("ファミリーマート", "food.convenience"),
    DictEntry("ファミマ", "food.convenience"),
    DictEntry("ミニストップ", "food.convenience"),
    DictEntry("ミニストツプ", "food.convenience"),  # OCR / 明細常见的大写ツ
    DictEntry("デイリーヤマザキ", "food.convenience"),
    DictEntry("ライフ", "food.groceries"),
    DictEntry("イオン", "food.groceries"),
    DictEntry("イトーヨーカドー", "food.groceries"),
    DictEntry("業務スーパー", "food.groceries"),
    DictEntry("業務用スーパー", "food.groceries"),
    DictEntry("オーケー", "food.groceries"),
    DictEntry("成城石井", "food.groceries"),
    DictEntry("マルエツ", "food.groceries"),
    DictEntry("サミット", "food.groceries"),
    DictEntry("西友", "food.groceries"),
    DictEntry("seiyu", "food.groceries"),
    DictEntry("ダイエー", "food.groceries"),
    DictEntry("全日食", "food.groceries"),
    DictEntry("ゼンニツシヨク", "food.groceries"),
    DictEntry("肉のハナマサ", "food.groceries"),
    DictEntry("コーヨー", "food.groceries"),
    DictEntry("ピーコック", "food.groceries"),
    DictEntry("東急ストア", "food.groceries"),
    DictEntry("阪急", "food.groceries"),
    DictEntry("マクドナルド", "food.dining"),
    DictEntry("マック", "food.dining"),
    DictEntry("モスバーガー", "food.dining"),
    DictEntry("サブウェイ", "food.dining"),
    DictEntry("すき家", "food.dining"),
    DictEntry("吉野家", "food.dining"),
    DictEntry("松屋", "food.dining"),
    DictEntry("なか卯", "food.dining"),
    DictEntry("ナカウ", "food.dining"),
    DictEntry("ガスト", "food.dining"),
    DictEntry("サイゼリヤ", "food.dining"),
    DictEntry("丸亀製麺", "food.dining"),
    DictEntry("くら寿司", "food.dining"),
    DictEntry("スシロー", "food.dining"),
    DictEntry("はま寿司", "food.dining"),
    DictEntry("ココイチ", "food.dining"),
    DictEntry("coco壱", "food.dining"),
    DictEntry("日高屋", "food.dining"),
    DictEntry("餃子の王将", "food.dining"),
    DictEntry("出前館", "food.dining"),
    DictEntry("ubereats", "food.dining"),
    DictEntry("uber eats", "food.dining"),
    DictEntry("スターバックス", "food.cafe"),
    DictEntry("スタバ", "food.cafe"),
    DictEntry("starbucks", "food.cafe"),
    DictEntry("ドトール", "food.cafe"),
    DictEntry("タリーズ", "food.cafe"),
    DictEntry("コメダ", "food.cafe"),
    DictEntry("サンマルク", "food.cafe"),

    # ---- 日用品 ----
    DictEntry("amazon", "daily.supplies"),
    DictEntry("アマゾン", "daily.supplies"),
    DictEntry("ダイソー", "daily.supplies"),
    DictEntry("セリア", "daily.supplies"),
    DictEntry("キャンドゥ", "daily.supplies"),
    DictEntry("無印良品", "daily.supplies"),
    DictEntry("ニトリ", "daily.furniture"),
    DictEntry("ikea", "daily.furniture"),
    DictEntry("ヨドバシ", "daily.furniture"),
    DictEntry("ビックカメラ", "daily.furniture"),
    DictEntry("ヤマダ電機", "daily.furniture"),
    DictEntry("ヤマダデンキ", "daily.furniture"),
    DictEntry("マツモトキヨシ", "daily.supplies"),
    DictEntry("マツキヨ", "daily.supplies"),
    DictEntry("ウエルシア", "daily.supplies"),
    DictEntry("スギ薬局", "daily.supplies"),
    DictEntry("ツルハ", "daily.supplies"),
    DictEntry("ドン・キホーテ", "daily.supplies"),
    DictEntry("ドンキ", "daily.supplies"),
    DictEntry("アカカベ", "daily.supplies"),
    DictEntry("メルカリ", "daily.supplies"),
    DictEntry("zozotown", "beauty.clothing"),

    # ---- 住居 ----
    DictEntry("家賃", "housing.rent"),
    DictEntry("ヤチン", "housing.rent"),
    DictEntry("引越", "housing"),
    DictEntry("ヒツコシ", "housing"),
    DictEntry("引っ越し", "housing"),
    DictEntry("管理費", "housing.management"),
    DictEntry("共益費", "housing.management"),

    # ---- 水道光熱費 ----
    DictEntry("東京電力", "utilities.electricity"),
    DictEntry("関西電力", "utilities.electricity"),
    DictEntry("中部電力", "utilities.electricity"),
    DictEntry("九州電力", "utilities.electricity"),
    DictEntry("東北電力", "utilities.electricity"),
    DictEntry("北海道電力", "utilities.electricity"),
    DictEntry("電気料金", "utilities.electricity"),
    DictEntry("電気", "utilities.electricity"),
    DictEntry("東京ガス", "utilities.gas"),
    DictEntry("大阪ガス", "utilities.gas"),
    DictEntry("ガス料金", "utilities.gas"),
    DictEntry("ガス", "utilities.gas"),
    DictEntry("水道局", "utilities.water"),
    DictEntry("水道料金", "utilities.water"),
    DictEntry("水道", "utilities.water"),

    # ---- 通信費 ----
    DictEntry("ドコモ", "comm.mobile"),
    DictEntry("docomo", "comm.mobile"),
    DictEntry("ソフトバンク", "comm.mobile"),
    DictEntry("softbank", "comm.mobile"),
    DictEntry("re:(?<![a-z])au(?![a-z])", "comm.mobile"),
    DictEntry("kddi", "comm.mobile"),
    DictEntry("楽天モバイル", "comm.mobile"),
    DictEntry("ワイモバイル", "comm.mobile"),
    DictEntry("uqモバイル", "comm.mobile"),
    DictEntry("ahamo", "comm.mobile"),
    DictEntry("povo", "comm.mobile"),
    DictEntry("linemo", "comm.mobile"),
    DictEntry("re:(?:フレッツ|ドコモ|ソフトバンク|au|ビッグローブ|so-net|nuro|eo)光", "comm.internet"),
    DictEntry("nuro", "comm.internet"),
    DictEntry("ocn", "comm.internet"),
    DictEntry("anthropic", "comm.subscription"),
    DictEntry("openai", "comm.subscription"),
    DictEntry("chatgpt", "comm.subscription"),
    DictEntry("github", "comm.subscription"),
    DictEntry("google", "comm.subscription"),
    DictEntry("apple.com/bill", "comm.subscription"),
    DictEntry("applecombill", "comm.subscription"),
    DictEntry("スクウェア・エニックス", "entertainment.hobby"),
    DictEntry("スクウェアエニックス", "entertainment.hobby"),
    DictEntry("icloud", "comm.subscription"),
    DictEntry("microsoft", "comm.subscription"),
    DictEntry("adobe", "comm.subscription"),
    DictEntry("プライム", "comm.subscription"),  # アマゾンプライム会費
    DictEntry("プライムカイヒ", "comm.subscription"),

    # ---- 娯楽 ----
    DictEntry("spotify", "entertainment.streaming"),
    DictEntry("netflix", "entertainment.streaming"),
    DictEntry("youtube", "entertainment.streaming"),
    DictEntry("disney", "entertainment.streaming"),
    DictEntry("hulu", "entertainment.streaming"),
    DictEntry("u-next", "entertainment.streaming"),
    DictEntry("abema", "entertainment.streaming"),
    DictEntry("dアニメ", "entertainment.streaming"),
    DictEntry("steam", "entertainment.hobby"),
    DictEntry("nintendo", "entertainment.hobby"),
    DictEntry("playstation", "entertainment.hobby"),
    DictEntry("博物館", "entertainment.hobby"),
    DictEntry("ハクブツカン", "entertainment.hobby"),
    DictEntry("美術館", "entertainment.hobby"),
    DictEntry("映画", "entertainment.hobby"),
    DictEntry("toho", "entertainment.hobby"),
    DictEntry("カラオケ", "entertainment.hobby"),
    DictEntry("ホテル", "entertainment.travel"),
    DictEntry("hotel", "entertainment.travel"),
    DictEntry("じゃらん", "entertainment.travel"),
    DictEntry("楽天トラベル", "entertainment.travel"),
    DictEntry("airbnb", "entertainment.travel"),
    DictEntry("booking.com", "entertainment.travel"),

    # ---- 交通費 ----
    DictEntry("etcカード", "transport.highway"),
    DictEntry("re:(?<![a-z])etc(?![a-z])", "transport.highway"),
    DictEntry("高速", "transport.highway"),
    DictEntry("nexco", "transport.highway"),
    DictEntry("eneos", "transport.fuel"),
    DictEntry("エネオス", "transport.fuel"),
    DictEntry("出光", "transport.fuel"),
    DictEntry("イデミツ", "transport.fuel"),
    DictEntry("アポロステーション", "transport.fuel"),
    DictEntry("コスモ石油", "transport.fuel"),
    DictEntry("エネクス", "transport.fuel"),
    DictEntry("昭和シェル", "transport.fuel"),
    DictEntry("ガソリン", "transport.fuel"),
    DictEntry("jr東日本", "transport.train_bus"),
    DictEntry("jr西日本", "transport.train_bus"),
    DictEntry("jr東海", "transport.train_bus"),
    DictEntry("東京メトロ", "transport.train_bus"),
    DictEntry("都営", "transport.train_bus"),
    DictEntry("大阪メトロ", "transport.train_bus"),
    DictEntry("osakametro", "transport.train_bus"),
    DictEntry("阪急", "transport.train_bus"),
    DictEntry("阪神", "transport.train_bus"),
    DictEntry("近鉄", "transport.train_bus"),
    DictEntry("南海", "transport.train_bus"),
    DictEntry("京阪", "transport.train_bus"),
    DictEntry("小田急", "transport.train_bus"),
    DictEntry("京王", "transport.train_bus"),
    DictEntry("東急", "transport.train_bus"),
    DictEntry("西武", "transport.train_bus"),
    DictEntry("東武", "transport.train_bus"),
    DictEntry("バス", "transport.train_bus"),
    DictEntry("タクシー", "transport.taxi"),
    DictEntry("re:(?<![a-z])go(?![a-z])(?:タクシー)?", "transport.taxi"),
    DictEntry("didi", "transport.taxi"),
    DictEntry("uber", "transport.taxi"),
    DictEntry("タイムズ", "transport.fuel"),  # 停车/租车归燃油交通
    DictEntry("パーキング", "transport.fuel"),

    # ---- 医療費 ----
    DictEntry("病院", "medical.consultation"),
    DictEntry("クリニック", "medical.consultation"),
    DictEntry("医院", "medical.consultation"),
    DictEntry("歯科", "medical.consultation"),
    DictEntry("薬局", "medical.medicine"),
    DictEntry("ドラッグ", "medical.medicine"),

    # ---- 教育 ----
    DictEntry("紀伊國屋", "education.books"),
    DictEntry("ジュンク堂", "education.books"),
    DictEntry("ブックオフ", "education.books"),
    DictEntry("kindle", "education.books"),
    DictEntry("udemy", "education.language"),
    DictEntry("duolingo", "education.language"),

    # ---- 衣服・美容 ----
    DictEntry("ユニクロ", "beauty.clothing"),
    DictEntry("uniqlo", "beauty.clothing"),
    DictEntry("re:(?<![a-z])gu(?![a-z])", "beauty.clothing"),
    DictEntry("しまむら", "beauty.clothing"),
    DictEntry("zara", "beauty.clothing"),
    DictEntry("h&m", "beauty.clothing"),
    DictEntry("アウトレット", "beauty.clothing"),
    DictEntry("ららぽーと", "beauty.clothing"),
    DictEntry("mop", "beauty.clothing"),  # 三井アウトレットパーク
    DictEntry("美容室", "beauty.salon"),
    DictEntry("美容院", "beauty.salon"),
    DictEntry("ヘアサロン", "beauty.salon"),
    DictEntry("qbハウス", "beauty.salon"),

    # ---- 税金・社会保険 ----
    DictEntry("シヤカイホケン", "tax.pension"),  # 社会保険料等（国民年金）
    DictEntry("社会保険", "tax.pension"),
    DictEntry("国民年金", "tax.pension"),
    DictEntry("ネンキン", "tax.pension"),
    DictEntry("年金", "tax.pension"),
    DictEntry("住民税", "tax.resident"),
    DictEntry("市民税", "tax.resident"),
    DictEntry("区民税", "tax.resident"),
    DictEntry("県民税", "tax.resident"),
    DictEntry("所得税", "tax.income"),
    DictEntry("国民健康保険", "tax.health_insurance"),
    DictEntry("健康保険", "tax.health_insurance"),
    DictEntry("介護保険", "tax.nursing_insurance"),

    # ---- 送金 ----
    DictEntry("wise", "remittance.overseas"),
    DictEntry("ワイズ", "remittance.overseas"),
    DictEntry("western union", "remittance.overseas"),
    DictEntry("海外送金", "remittance.overseas"),
    DictEntry("仕送り", "remittance.family"),
    DictEntry("送金手数料", "remittance.fee"),

    # ---- 収入 ----
    DictEntry("給与", "income.salary"),
    DictEntry("給料", "income.salary"),
    DictEntry("キュウヨ", "income.salary"),
    DictEntry("賞与", "income.bonus"),
    DictEntry("ボーナス", "income.bonus"),
    DictEntry("還付", "income.refund"),
    DictEntry("返金", "income.refund"),
    DictEntry("利息", "income.other"),
    DictEntry("外国関係", "income.other"),  # 海外汇入
    DictEntry("返品", "income.refund"),
    DictEntry("配当", "income.other"),

    # ---- 兜底：店名里带的业态词。放在最后，只有前面全部不命中才轮到 ----
    DictEntry("焼肉", "food.dining"),
    DictEntry("ヤキニク", "food.dining"),
    DictEntry("寿司", "food.dining"),
    DictEntry("スシ", "food.dining"),
    DictEntry("ズシ", "food.dining"),
    DictEntry("ラーメン", "food.dining"),
    DictEntry("麺屋", "food.dining"),
    DictEntry("うどん", "food.dining"),
    DictEntry("そば", "food.dining"),
    DictEntry("食堂", "food.dining"),
    DictEntry("弁当", "food.dining"),
    DictEntry("串カツ", "food.dining"),
    DictEntry("洋食", "food.dining"),
    DictEntry("丼", "food.dining"),
    DictEntry("居酒屋", "food.dining"),
    DictEntry("ダイニング", "food.dining"),
    DictEntry("レストラン", "food.dining"),
    DictEntry("キッチン", "food.dining"),
    DictEntry("パスタ", "food.dining"),
    DictEntry("カレー", "food.dining"),
    DictEntry("珈琲", "food.cafe"),
    DictEntry("コーヒー", "food.cafe"),
    DictEntry("カフェ", "food.cafe"),
    DictEntry("パティスリー", "food.cafe"),
    DictEntry("ベーカリー", "food.cafe"),
    DictEntry("ビール", "food.dining"),
    DictEntry("スーパー", "food.groceries"),
    DictEntry("マーケット", "food.groceries"),
    DictEntry("マルシェ", "food.groceries"),
    DictEntry("デリ", "food.groceries"),
    DictEntry("サービスエリア", "food.dining"),
    DictEntry("道の駅", "food.groceries"),
    DictEntry("ホテル", "entertainment.travel"),
    DictEntry("温泉", "entertainment.travel"),
    DictEntry("パーク", "entertainment.hobby"),
    DictEntry("ミュージアム", "entertainment.hobby"),
    DictEntry("公園", "entertainment.hobby"),
    DictEntry("手数料", "other"),
)


def _norm(p: str) -> str:
    """词典模式必须走与商家名**完全相同**的规范化管道。

    否则规范化规则一变（如片假名后的连字符归一为长音），词典就集体失效：
    「セブン-イレブン」规范化后是「セブンーイレブン」，若模式只做小写去空格，
    就永远匹配不到。规范化结果为空的模式（如会被当作支付前缀剥掉的 "visa"）
    退回简单形式。
    """
    from app.services.normalize import normalize_merchant

    full = normalize_merchant(p)
    return full or re.sub(r"\s+", "", p.lower())


_COMPILED: list[tuple[re.Pattern[str] | str, DictEntry]] = []
for entry in ENTRIES:
    if entry.pattern.startswith("re:"):
        _COMPILED.append((re.compile(entry.pattern[3:]), entry))
    else:
        _COMPILED.append((_norm(entry.pattern), entry))


def lookup(merchant_norm: str) -> DictEntry | None:
    """按规范化商家名查词典。返回第一个命中的条目，无命中返回 None。"""
    for entry in lookup_all(merchant_norm):
        return entry
    return None


def lookup_all(merchant_norm: str):
    """按优先级依次产出所有命中的条目。

    调用方可以跳过方向不符的条目再取下一个：「ポイント獲得 一蘭」先命中「一蘭」
    （餐饮，支出类），但这行是收入，应继续取到「ポイント獲得」（收入类）。
    """
    if not merchant_norm:
        return
    for needle, entry in _COMPILED:
        if isinstance(needle, str):
            if needle in merchant_norm:
                yield entry
        elif needle.search(merchant_norm):
            yield entry
