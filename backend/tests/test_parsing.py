"""文本行解析的测试。

夹具是 docs/测试图片/ 里 9 张真实截图的逐字转录——一行对应截图上的一个文本块，
顺序自上而下。它们就是需求书附录 A 的回归基准。
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.parsing.amounts import parse_amount, parse_amounts, trailing_sign
from app.services.parsing.dates import infer_year, parse_date, parse_year_month
from app.services.parsing.lines import parse_lines

TODAY = dt.date(2026, 9, 14)

# --------------------------------------------------------------------------
# 截图转录
# --------------------------------------------------------------------------

OLIVE_OCT = """
21:27
利用明細
クレジット
デビット
ポイント払い
Olive
他のカードを選択
2026年10月
2026年10月26日
お支払い金額（未確定）
1,502円
ライフ此花伝法店
842円
26.09.02
1回払い
ミニストップ　日本橋３丁目交差点東店
230円
26.09.02
1回払い
ミニストップ　日本橋３丁目交差点東店
230円
26.09.01
1回払い
関西電力電気２０２６／０９
200円
26.08.26
1回払い
"""

OLIVE_SEP = """
利用明細
2026年9月
2026年9月28日
お支払い金額（未確定）
68,813円
ＡＮＴＨＲＯＰＩＣ＊　ＣＬＡＵＤＥ
3,652円
ＳＵ
1回払い
26.08.31
ライフ此花伝法店
1,841円
1回払い
26.08.31
ＳＰＯＴＩＦＹ　Ｐ４６４２０７４Ａ
1,080円
７
1回払い
26.08.30
ＡＭＡＺＯＮ．ＣＯ．ＪＰ
3,064円
1回払い
26.08.29
"""

SMBC_BANK = """
残高別普通
21:26 現在
オリーブＡＳＨ　支店 3396840
預金残高
50,073円
お支払可能金額 50,073 円
期間・キーワード検索
2026.09
振込　ｱﾏｿﾞﾝｼﾞﾔﾊﾟﾝ(ﾄﾞ 2,402 円 +
26.09.07 残高 50,073 円
振込　ｱﾏｿﾞﾝｼﾞﾔﾊﾟﾝ(ﾄﾞ 1 円 +
26.09.02 残高 47,671 円
PE ｼﾔｶｲﾎｹﾝﾘﾖｳﾄｳ(ｺﾂｷﾝ) 41,208 円 −
26.09.01 残高 47,670 円
振込　ﾑ-ﾑ-ｼﾖｳｹﾝ(ｶ 68,186 円 +
26.09.01 残高 88,878 円
2026.08
ﾗｸﾃﾝｶｰﾄﾞｻｰﾋﾞｽ 25,980 円 −
26.08.27 残高 20,692 円
ホーム
口座一覧
振込・振替
資産管理
メニュー
"""

RAKUTEN_1 = """
**** 1371
変更する
2026/09
¥ 16,907
今月のお支払金額を調整する
家計簿に保存
絞り込み
新しい順
JCB ミニストツプ
2026/08/20 1回払い
¥ 770
JCB ミニストツプ
1回払い
¥ 697
JCB ミニストツプ
1回払い
¥ 165
JCB トヨタハクブツカン エスビー
1回払い
¥ 1,200
JCB ヨロジヨウロウエスエ-クダリ
2026/08/15 1回払い
¥ 1,380
ENEOS（J） 99993 6342
2026/08/15 1回払い
¥ 1,156
JCB ヒラメテイ
2026/08/14 1回払い
¥ 4,994
イデミツ（アポロステーション） 0.00
1回払い
¥ 867
"""

RAKUTEN_2 = """
2026/09
¥ 16,907
今月のお支払金額を調整する
ETCカード売上 ホウライ　　　ニシイシキリホンセ
2026/08/02 1回払い
¥ 620
ETCカード売上 ニシイシキリホンセン ホウライ
2026/08/02 1回払い
¥ 620
ETCカード売上 ヒガシオオサカイリ テンポウザンシ
2026/08/02 1回払い
¥ 790
ETCカード売上 ワンガンマイシマ　ヒガシオオサ…
2026/08/02 1回払い
¥ 840
ETCカード売上 シマヤ　　　モリシヨウジデ
2026/07/26 1回払い
¥ 770
ETCカード売上 シヨウレンジガワ ヒメジマデ
2026/07/12 1回払い
¥ 280
楽天モバイル製品代　704861
2025/03/27 分割48回払い(17回目)
ご利用金額 ¥ 41,487
おすすめ情報
"""

JWEST_AUG = """
ビックカメラＪ－ＷＥＳＴカード（ベーシック）
5月
6月
7月
8月
9月
10月
お支払明細
伊藤忠エネクス
6月13日 1回払い
1,006円
モバイルＩＣＯＣＡ　チャージ
6月16日 ボーナス
2,000円
ららぽーと門真／ＭＯＰ大阪門真
6月23日 1回払い
2,331円
ららぽーと門真／ＭＯＰ大阪門真
6月23日 1回払い
7,949円
アマゾンプライムカイヒ
6月26日 1回払い
600円
ＡＰ／ＱＰ／ダイエー　エスエム
6月28日 1回払い
479円
アートヒツコシセンターカブシキガイシ
6月29日 1回払い
71,113円
ゼンニツシヨクチエーントリシマテン
6月30日 1回払い
3,331円
ナカウ
7月1日 1回払い
510円
"""

JWEST_SEP = """
ビックカメラＪ－ＷＥＳＴカード（ベーシック）
9月
ご請求内訳
通常
9,486 円
リボ
− 円
分割
− 円
事前お支払額
0 円
お支払明細
アマゾンプライムカイヒ
7月26日 1回払い
600円
ソフトバンク（Ｂ）
8月9日 1回払い
8,886円
詳細を見る
"""

PAYPAY = """
取引履歴
すべて
PayPay残高
PayPayカード
残高
残高カード
2026年5月
Steam
1,000円
2026年5月26日 0時54分
残高
支払い失敗
Steam
620円
2026年5月13日 21時56分
残高
支払い完了
大阪市水道局（水道料金、下水道使用
1,595円
料、修繕料、給水装置工事費）
2026年5月13日 21時52分
残高
支払い完了
Steam
1,540円
2026年5月13日 21時51分
残高
支払い完了
Steam
921円
2026年5月11日 22時01分
"""


def _kept(result):
    return [t for t in result.transactions if not t.excluded]


def _excluded(result):
    return [t for t in result.transactions if t.excluded]


# --------------------------------------------------------------------------
# 日期
# --------------------------------------------------------------------------


class TestDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2026/09/07", dt.date(2026, 9, 7)),
            ("2026-09-07", dt.date(2026, 9, 7)),
            ("2026.09.07", dt.date(2026, 9, 7)),
            ("2026年9月7日", dt.date(2026, 9, 7)),
            ("２０２６／０９／０７", dt.date(2026, 9, 7)),
            ("26.09.02", dt.date(2026, 9, 2)),
            ("26/09/02", dt.date(2026, 9, 2)),
            ("令和8年9月7日", dt.date(2026, 9, 7)),
            ("R8.9.7", dt.date(2026, 9, 7)),
            ("令和元年5月1日", dt.date(2019, 5, 1)),
            ("2026/08/20 1回払い", dt.date(2026, 8, 20)),
            ("9/7(月)", dt.date(2026, 9, 7)),
        ],
    )
    def test_formats(self, text, expected):
        p = parse_date(text, today=TODAY)
        assert p is not None and p.date == expected

    def test_time_extracted(self):
        p = parse_date("2026年5月26日 0時54分", today=TODAY)
        assert p.time == dt.time(0, 54)

    def test_no_year_with_anchor(self):
        """J-WEST：8 月支払分里的「6月13日」应推断为同年 6 月。"""
        p = parse_date("6月13日 1回払い", anchor=dt.date(2026, 8, 1), today=TODAY)
        assert p.date == dt.date(2026, 6, 13)
        assert p.year_inferred

    def test_no_year_crosses_year_boundary(self):
        """1 月支払分里的「12月20日」是上一年的消费。"""
        assert infer_year(12, 20, anchor=dt.date(2027, 1, 1)) == 2026

    def test_no_year_without_anchor_not_in_future(self):
        # 今天是 9/14；「11月3日」若取今年会落在未来，应取去年
        assert infer_year(11, 3, anchor=None, today=TODAY) == 2025
        assert infer_year(9, 1, anchor=None, today=TODAY) == 2026

    def test_year_month_header(self):
        assert parse_year_month("2026年10月") == dt.date(2026, 10, 1)
        assert parse_year_month("2026.09") == dt.date(2026, 9, 1)
        assert parse_year_month("2026/09/07") is None  # 完整日期不是标题


# --------------------------------------------------------------------------
# 金额
# --------------------------------------------------------------------------


class TestAmounts:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("¥1,234", 1234),
            ("1,234円", 1234),
            ("¥ 620", 620),
            ("１，２３４円", 1234),
            ("△1,234", -1234),
            ("▲1,234", -1234),
            ("-1,234", -1234),
            ("−1,234", -1234),
            ("(1,234)", -1234),
            ("1234", 1234),
            ("", None),
            ("-", None),
            ("−", None),
        ],
    )
    def test_single(self, text, expected):
        assert parse_amount(text) == expected

    def test_decimal_is_not_yen(self):
        """イデミツ 那行的「0.00」不是金额，真实金额在下一行（附录 A.2.3）。"""
        found = parse_amounts("イデミツ（アポロステーション） 0.00")
        assert found == []

    def test_balance_label_is_separated(self):
        found = parse_amounts("26.09.07 残高 50,073 円")
        assert [a.is_balance for a in found] == [True]

    def test_trailing_sign(self):
        assert trailing_sign("振込 ｱﾏｿﾞﾝ 2,402 円 +") == "income"
        assert trailing_sign("PE ｼﾔｶｲﾎｹﾝ 41,208 円 −") == "expense"
        assert trailing_sign("ローソン 500円") is None


# --------------------------------------------------------------------------
# 行解析：逐张截图
# --------------------------------------------------------------------------


class TestOlive:
    def test_october_statement(self):
        r = parse_lines(OLIVE_OCT, today=TODAY)
        kept = _kept(r)
        assert [(t.merchant_raw, t.amount, t.date) for t in kept] == [
            ("ライフ此花伝法店", 842, dt.date(2026, 9, 2)),
            ("ミニストップ 日本橋3丁目交差点東店", 230, dt.date(2026, 9, 2)),
            ("ミニストップ 日本橋3丁目交差点東店", 230, dt.date(2026, 9, 1)),
            ("関西電力電気2026/09", 200, dt.date(2026, 8, 26)),
        ]
        # 合计行被排除且说明了原因，不是静默丢弃
        summary = [t for t in _excluded(r) if t.exclude_reason == "summary_row"]
        assert any(t.amount == 1502 for t in summary)
        # 两位年份不是推断
        assert all(not t.date_inferred for t in kept)

    def test_merchant_continuation(self):
        """附录 A.3.3：ＡＮＴＨＲＯＰＩＣ＊ ＣＬＡＵＤＥ / ＳＵ 跨两行。"""
        r = parse_lines(OLIVE_SEP, today=TODAY)
        kept = _kept(r)
        merchants = [t.merchant_raw for t in kept]
        assert merchants[0] == "ANTHROPIC* CLAUDE SU"
        assert kept[0].amount == 3652
        assert kept[0].date == dt.date(2026, 8, 31)
        # SPOTIFY P4642074A / 7 同理
        assert merchants[2] == "SPOTIFY P4642074A 7"
        assert len(kept) == 4


class TestSmbcBank:
    def test_direction_from_trailing_sign(self):
        # 解析器整行做 NFKC，因此 merchant_raw 是半角片假名转全角后的形式；
        # 逐字原文保留在 raw_text，规范化管道（normalize_merchant）本就会做同样的转换
        r = parse_lines(SMBC_BANK, today=TODAY)
        kept = _kept(r)
        assert [(t.merchant_raw, t.amount, t.direction) for t in kept] == [
            ("振込 アマゾンジヤパン(ド", 2402, "income"),
            ("振込 アマゾンジヤパン(ド", 1, "income"),
            ("PE シヤカイホケンリヨウトウ(コツキン)", 41208, "expense"),
            ("振込 ム-ム-シヨウケン(カ", 68186, "income"),
            ("ラクテンカードサービス", 25980, "expense"),
        ]

    def test_per_row_balance(self):
        """附录 A.3.6：每行残高被单独提取，可用于逐行对账。"""
        r = parse_lines(SMBC_BANK, today=TODAY)
        kept = _kept(r)
        assert [t.balance_after for t in kept] == [50073, 47671, 47670, 88878, 20692]
        # 逐行校验：残高[i] − 残高[i+1] == 带符号金额[i]
        for a, b in zip(kept, kept[1:]):
            signed = a.amount if a.direction == "income" else -a.amount
            assert a.balance_after - b.balance_after == signed

    def test_top_balance_detected(self):
        r = parse_lines(SMBC_BANK, today=TODAY)
        assert r.detected_balance == 50073

    def test_group_header_gives_anchor_and_dates(self):
        r = parse_lines(SMBC_BANK, today=TODAY)
        kept = _kept(r)
        assert kept[0].date == dt.date(2026, 9, 7)
        assert kept[-1].date == dt.date(2026, 8, 27)


class TestRakutenCard:
    def test_date_inheritance(self):
        """附录 A.3.1：连续同日交易只有第一条显示日期，其余向上继承。"""
        r = parse_lines(RAKUTEN_1, today=TODAY)
        kept = _kept(r)
        assert [(t.merchant_raw, t.amount) for t in kept[:4]] == [
            ("JCB ミニストツプ", 770),
            ("JCB ミニストツプ", 697),
            ("JCB ミニストツプ", 165),
            ("JCB トヨタハクブツカン エスビー", 1200),
        ]
        assert [t.date for t in kept[:4]] == [dt.date(2026, 8, 20)] * 4
        assert [t.date_inferred for t in kept[:4]] == [False, True, True, True]
        # 继承日期的行置信度更低
        assert kept[1].confidence < kept[0].confidence

    def test_decimal_noise_ignored(self):
        """イデミツ 行的「0.00」不是金额；真实金额 867 在两行之后。"""
        r = parse_lines(RAKUTEN_1, today=TODAY)
        idemitsu = next(t for t in _kept(r) if "イデミツ" in t.merchant_raw)
        assert idemitsu.amount == 867
        assert idemitsu.date == dt.date(2026, 8, 14)  # 继承自上一行 ヒラメテイ

    def test_amount_after_date_layout(self):
        r = parse_lines(RAKUTEN_1, today=TODAY)
        eneos = next(t for t in _kept(r) if "ENEOS" in t.merchant_raw)
        assert eneos.amount == 1156
        assert eneos.date == dt.date(2026, 8, 15)

    def test_etc_round_trip_stays_two_rows(self):
        """附录 A.4.1：往返两程是两笔，解析层不得合并。"""
        r = parse_lines(RAKUTEN_2, today=TODAY)
        kept = _kept(r)
        etc620 = [t for t in kept if t.amount == 620]
        assert len(etc620) == 2
        assert etc620[0].merchant_raw != etc620[1].merchant_raw

    def test_installment(self):
        """附录 A.5.1：分期只有总额可见时按 总额÷期数 估算并标记。"""
        r = parse_lines(RAKUTEN_2, today=TODAY)
        mobile = next(t for t in _kept(r) if "楽天モバイル" in t.merchant_raw)
        assert mobile.installment == {
            "total_times": 48,
            "current_time": 17,
            "total_amount": 41487,
            "estimated": True,
        }
        assert mobile.amount == round(41487 / 48)
        assert mobile.date == dt.date(2025, 3, 27)
        assert any(w.startswith("installment_estimated") for w in r.warnings)

    def test_page_chrome_not_transactions(self):
        r = parse_lines(RAKUTEN_2, today=TODAY)
        merchants = [t.merchant_raw for t in r.transactions]
        assert not any("おすすめ" in m or "調整" in m for m in merchants)


class TestJwest:
    def test_year_inferred_from_statement_month(self):
        """附录 A.3.2：无年份日期 + 「8月」支払月 Tab → 推断年份。"""
        r = parse_lines(JWEST_AUG, statement_month=dt.date(2026, 8, 1), today=TODAY)
        kept = _kept(r)
        assert kept[0].merchant_raw == "伊藤忠エネクス"
        assert kept[0].date == dt.date(2026, 6, 13)
        assert kept[0].date_inferred
        assert kept[-1].date == dt.date(2026, 7, 1)
        assert len(kept) == 9

    def test_bonus_payment_label_stripped(self):
        r = parse_lines(JWEST_AUG, statement_month=dt.date(2026, 8, 1), today=TODAY)
        icoca = next(t for t in _kept(r) if "ICOCA" in t.merchant_raw)
        assert icoca.merchant_raw == "モバイルICOCA チャージ"
        assert icoca.amount == 2000

    def test_summary_block_excluded(self):
        """附录 A.2.2：「ご請求内訳」下的 通常 / リボ / 分割 不是交易。"""
        r = parse_lines(JWEST_SEP, statement_month=dt.date(2026, 9, 1), today=TODAY)
        kept = _kept(r)
        assert [(t.merchant_raw, t.amount) for t in kept] == [
            ("アマゾンプライムカイヒ", 600),
            ("ソフトバンク(B)", 8886),
        ]
        reasons = {t.merchant_raw: t.exclude_reason for t in _excluded(r)}
        assert reasons.get("通常") == "summary_row"
        # 「− 円」表示空值，不是负数金额
        assert all(t.amount != 0 or t.excluded for t in r.transactions)


class TestPayPay:
    def test_failed_payment_excluded(self):
        """附录 A.2.1：「支払い失敗」的 Steam 1,000 円绝不能入账。"""
        r = parse_lines(PAYPAY, today=TODAY)
        failed = [t for t in _excluded(r) if t.exclude_reason == "payment_failed"]
        assert len(failed) == 1
        assert failed[0].amount == 1000
        assert failed[0].date == dt.date(2026, 5, 26)
        # 排除的行仍然带着信息回传，供待确认区告知用户
        kept_amounts = [t.amount for t in _kept(r)]
        assert 1000 not in kept_amounts

    def test_kept_rows_with_time(self):
        r = parse_lines(PAYPAY, today=TODAY)
        kept = _kept(r)
        assert [(t.merchant_raw, t.amount, t.time) for t in kept] == [
            ("Steam", 620, dt.time(21, 56)),
            ("大阪市水道局(水道料金、下水道使用 料、修繕料、給水装置工事費)", 1595, dt.time(21, 52)),
            ("Steam", 1540, dt.time(21, 51)),
            ("Steam", 921, dt.time(22, 1)),
        ]

    def test_merchant_continuation_around_amount(self):
        """大阪市水道局 的名称被金额行隔开后仍能合并（附录 A.3.3）。"""
        r = parse_lines(PAYPAY, today=TODAY)
        water = next(t for t in _kept(r) if "水道局" in t.merchant_raw)
        assert "給水装置工事費" in water.merchant_raw
