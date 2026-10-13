"""商家名规范化与指纹的测试。

用例大多直接取自 docs/测试图片/ 里的真实截图（需求书附录 A），
它们是识别与去重功能的回归基准。
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.normalize import make_fingerprint, normalize_merchant, similarity


class TestNfkc:
    """步骤 1：Unicode NFKC 正规化。"""

    def test_fullwidth_alphanumeric(self):
        # Olive 明細：ＡＭＡＺＯＮ．ＣＯ．ＪＰ
        assert normalize_merchant("ＡＭＡＺＯＮ．ＣＯ．ＪＰ") == "amazon.co.jp"

    def test_halfwidth_katakana(self):
        # 三井住友銀行：ﾗｸﾃﾝｶｰﾄﾞｻｰﾋﾞｽ（半角片假名 → 全角）
        assert normalize_merchant("ﾗｸﾃﾝｶｰﾄﾞｻｰﾋﾞｽ") == "ラクテンカードサービス"

    def test_halfwidth_katakana_with_dakuten(self):
        # 浊点为独立字符，NFKC 需正确合成：ﾀﾞｲｿｰ → ダイソー
        assert normalize_merchant("ﾀﾞｲｿｰ") == "ダイソー"

    def test_fullwidth_space_removed(self):
        # Olive：ミニストップ　日本橋３丁目交差点東店（全角空格 U+3000）；小写ッ归一为ツ
        assert (
            normalize_merchant("ミニストップ　日本橋３丁目交差点東店")
            == "ミニストツプ日本橋3丁目交差点東店"
        )

    def test_small_kana_and_horizontal_bar_unified(self):
        # 三井住友カード 明细把 ファミリーマート 写成「フアミリ―マ―ト」（U+2015 + 大写ア），
        # 与 App 截图里的「ファミリーマート」必须归一到同一形式
        assert normalize_merchant("フアミリ―マ―トシミズニチヨウメ").startswith("フアミリーマート")
        assert normalize_merchant("ファミリーマート") == "フアミリーマート"
        assert normalize_merchant("ミニストツプ") == normalize_merchant("ミニストップ")

    def test_trailing_payment_method_stripped(self):
        # 「／ＮＦＣ」「／ｉＤ」「●」是刷卡方式，不是店名的一部分
        assert normalize_merchant("V280720　自販機（ＪＡＭＡ）／ｉＤ") == "自販機(jama)"
        assert normalize_merchant("モバイルＳｕｉｃａ（ＡｐｐｌｅＶ）●") == "モバイルsuica"
        assert normalize_merchant("ホワイティうめだ／ＮＦＣ") == "ホワイテイうめだ"

    def test_never_empty_for_nonempty_input(self):
        # 银行明细里的占位「V000000」：全部被当传票号剥掉后要有退路，
        # 否则这类行指纹相同、彼此判成重复
        assert normalize_merchant("V000000") == "v000000"

    def test_brand_key_takes_part_before_separator(self):
        from app.services.normalize import merchant_brand

        assert merchant_brand("一蘭 - 一蘭　立川店") == "一蘭"
        assert merchant_brand("ロフト - 吉祥寺ロフト") == "ロフト"
        # 没有分隔符时与规范化名一致
        assert merchant_brand("すき家 新宿店") == normalize_merchant("すき家 新宿店")

    def test_fullwidth_slash(self):
        # J-WEST：ららぽーと門真／ＭＯＰ大阪門真
        assert normalize_merchant("ららぽーと門真／ＭＯＰ大阪門真") == "ららぽーと門真/mop大阪門真"


class TestPrefixStripping:
    """步骤 4–5：支付渠道前缀与法人格。"""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("JCB ミニストツプ", "ミニストツプ"),
            ("V/ローソン", "ローソン"),
            ("ＡＰ／ＱＰ／ダイエー　エスエム", "ダイエー エスエム".replace(" ", "")),
        ],
    )
    def test_payment_prefix(self, raw: str, expected: str):
        assert normalize_merchant(raw) == expected

    def test_corporate_affix(self):
        assert normalize_merchant("カ)アートヒツコシセンター") == "アートヒツコシセンター"
        assert normalize_merchant("（株）ライフ") == "ライフ"


class TestTrailingStripping:
    """步骤 6–7：末尾年月与店铺编号。"""

    def test_trailing_store_number(self):
        # 楽天カード：ENEOS（J）99993 6342
        assert normalize_merchant("ENEOS（J）99993 6342") == "eneos(j)"

    def test_trailing_year_month(self):
        # Olive：関西電力電気２０２６／０９
        # 不剥离的话，每月电费都会成为一个新商家，商家记忆永远学不会
        assert normalize_merchant("関西電力電気２０２６／０９") == "関西電力電気"
        assert normalize_merchant("東京ガス2026年9月") == "東京ガス"

    def test_short_trailing_digits_kept(self):
        # 2 位数字不视为店铺编号，避免误伤「セブン-イレブン12」之类
        assert normalize_merchant("テスト12") == "テスト12"


class TestOrderPreservation:
    """附录 A.4.1：规范化必须保序 —— 这是最重要的一条约束。"""

    def test_etc_round_trip_must_not_collapse(self):
        """高速公路 ETC 往返两程：同日、同额、词元相同但顺序相反。

        它们是真实的两笔交易。若规范化对词元排序，二者会得到相同结果
        并被错误合并，导致少记一笔支出。
        """
        outbound = normalize_merchant("ETCカード売上 ホウライ　　　ニシイシキリホンセ")
        inbound = normalize_merchant("ETCカード売上 ニシイシキリホンセン ホウライ")

        assert outbound != inbound, "词序颠倒的两笔被规范化成了同一个值——规范化管道引入了无序化处理"

        # 指纹也必须不同，否则 L1/L2 会自动合并
        fp_out = make_fingerprint(dt.date(2026, 8, 2), "expense", 620, outbound)
        fp_in = make_fingerprint(dt.date(2026, 8, 2), "expense", 620, inbound)
        assert fp_out != fp_in


class TestFingerprint:
    def test_same_transaction_same_fingerprint(self):
        a = make_fingerprint(dt.date(2026, 9, 2), "expense", 230, "ミニストップ")
        b = make_fingerprint(dt.date(2026, 9, 2), "expense", 230, "ミニストップ")
        assert a == b

    def test_different_date_different_fingerprint(self):
        """Olive 样本：09/01 与 09/02 各一笔 230 円 ミニストップ，是真实的两笔。

        指纹必须不同，它们只应触发 L3b 的「可能重复」黄标，
        而不是被当作同一笔。
        """
        d1 = make_fingerprint(dt.date(2026, 9, 1), "expense", 230, "ミニストップ日本橋3丁目交差点東店")
        d2 = make_fingerprint(dt.date(2026, 9, 2), "expense", 230, "ミニストップ日本橋3丁目交差点東店")
        assert d1 != d2

    def test_direction_matters(self):
        """同日同额的收入与支出不是同一笔（如退款与消费）。"""
        exp = make_fingerprint(dt.date(2026, 9, 1), "expense", 1000, "テスト")
        inc = make_fingerprint(dt.date(2026, 9, 1), "income", 1000, "テスト")
        assert exp != inc


class TestSimilarity:
    def test_identical(self):
        assert similarity("ローソン", "ローソン") == 1.0

    def test_store_suffix_difference_is_high(self):
        """同一家店多出店铺后缀，应判为高相似（L3b 需要能命中）。"""
        assert similarity("ミニストップ", "ミニストップ日本橋3丁目交差点東店") >= 0.4

    def test_reversed_tokens_lower_than_identical(self):
        """词序颠倒的相似度必须低于完全相同。"""
        a = "ホウライニシイシキリホンセ"
        b = "ニシイシキリホンセンホウライ"
        assert similarity(a, b) < 1.0

    def test_empty(self):
        assert similarity("", "ローソン") == 0.0
