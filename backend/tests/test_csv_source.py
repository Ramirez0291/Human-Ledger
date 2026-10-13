"""CSV 来源的测试。

夹具按三井住友カード / 三井住友銀行 / 楽天カード / PayPay 导出文件的**格式**构造（Shift_JIS、列结构、
合计行、退款行、占位行），内容为虚构数据。真实文件含个人信息，不进仓库。
"""

from __future__ import annotations

import datetime as dt

from app.services.importing.csv_source import (
    PAYPAY,
    RAKUTEN_CARD,
    SMBC_BANK,
    SMBC_CARD,
    ColumnMapping,
    decode,
    detect,
    parse_csv,
    read_rows,
    suggest_mapping,
)

# 三井住友カード：首行持卡人信息（无列标题），末尾合计行，含退款与海外交易
SMBC_CARD_CSV = (
    "ＴＥＳＴ　ＴＡＲＯ　様,4980-09**-****-****,Ｏｌｉｖｅ／クレジット\r\n"
    "2025/08/01,ＺＯＺＯＴＯＷＮ,3665,１,１,3665,\r\n"
    "2025/08/02,セブン−イレブン,226,１,１,226,\r\n"
    "2025/08/09,関西電力電気２０２５／０８,7614,１,１,7614,\r\n"
    "2025/08/19,ＡＭＡＺＯＮ．ＣＯ．ＪＰ,-5375,１,１,-5375,返品\r\n"
    "2025/08/20,楽天モバイル製品代,41487,分割,48,864,\r\n"
    "2025/08/30,SPOTIFY P3A0A053BD (STOCKHOLM ),980,１,１,980,980.00　JPY　1.0000　08 30\r\n"
    ",,,,,8874,\r\n"
).encode("cp932")

# 三井住友銀行 口座明細：固定表头，出金/入金分列，逐行残高，末尾占位行
SMBC_BANK_CSV = (
    "年月日,お引出し,お預入れ,お取り扱い内容,残高,メモ,ラベル\r\n"
    '2026/9/7,,2402,"振込　ｱﾏｿﾞﾝｼﾞﾔﾊﾟﾝ(ﾄﾞ",50073,"",\r\n'
    '2026/9/1,41208,,"PE ｼﾔｶｲﾎｹﾝﾘﾖｳﾄｳ(ｺﾂｺｷﾝ)",47671,"",\r\n'
    '2026/8/27,25980,,"ﾗｸﾃﾝｶ-ﾄﾞｻ-ﾋﾞｽ",88879,"",\r\n'
    '2026/8/27,,30000,"カード　(756)",114859,"",\r\n'
    '2026/8/25,,231685,"給料振込　ｶ)ﾃｽﾄｶﾝﾊﾟﾆｰ",84859,"",\r\n'
    '2026/6/30,68000,,"ﾔﾁﾝ",-146826,"",\r\n'
    '2024/3/30,,0,"　",0,"",\r\n'
).encode("cp932")

# 未知银行的通用格式（UTF-8 BOM）
GENERIC_CSV = "﻿取引日,摘要,出金額,入金額,残高\n2026-09-01,ローソン,500,,10000\n2026-09-02,給与,,250000,260000\n".encode(
    "utf-8"
)


class TestDecode:
    def test_shift_jis(self):
        text, enc = decode(SMBC_BANK_CSV)
        assert enc == "cp932"
        assert text.startswith("年月日")

    def test_utf8_bom(self):
        text, enc = decode(GENERIC_CSV)
        assert enc == "utf-8-sig"
        assert text.startswith("取引日")


class TestDetect:
    def test_smbc_card(self):
        det = detect(read_rows(decode(SMBC_CARD_CSV)[0]), "202509.csv")
        assert det.profile is SMBC_CARD
        assert det.statement_month == dt.date(2025, 9, 1)
        assert det.mapping.has_header is False

    def test_smbc_bank(self):
        det = detect(read_rows(decode(SMBC_BANK_CSV)[0]), "meisai.csv")
        assert det.profile is SMBC_BANK
        assert det.mapping.withdrawal == 1 and det.mapping.deposit == 2 and det.mapping.balance == 4

    def test_generic_by_header(self):
        det = detect(read_rows(decode(GENERIC_CSV)[0]))
        assert det.profile is None
        m = det.mapping
        assert (m.date, m.merchant, m.withdrawal, m.deposit, m.balance) == (0, 1, 2, 3, 4)

    def test_suggest_mapping_needs_date_and_merchant(self):
        assert suggest_mapping(["金額", "備考"]) is None


class TestSmbcCard:
    def test_rows(self):
        result, det, _ = parse_csv(SMBC_CARD_CSV, "202509.csv")
        kept = [t for t in result.transactions if not t.excluded]
        assert [(t.date, t.amount, t.direction) for t in kept] == [
            (dt.date(2025, 8, 1), 3665, "expense"),
            (dt.date(2025, 8, 2), 226, "expense"),
            (dt.date(2025, 8, 9), 7614, "expense"),
            (dt.date(2025, 8, 19), 5375, "income"),  # 退款
            (dt.date(2025, 9, 20), 864, "expense"),  # 分期：当期金额，记在支払月
            (dt.date(2025, 8, 30), 980, "expense"),
        ]
        assert result.statement_month == "2025-09"

    def test_total_row_excluded_as_summary(self):
        result, _, _ = parse_csv(SMBC_CARD_CSV, "202509.csv")
        summary = [t for t in result.transactions if t.exclude_reason == "summary_row"]
        assert len(summary) == 1 and summary[0].amount == 8874

    def test_installment_uses_this_month_amount(self):
        """附录 A.5.1：回数 > 1 时，今回請求額才是当期金额，利用金額是总额。"""
        result, _, _ = parse_csv(SMBC_CARD_CSV, "202509.csv")
        mobile = next(t for t in result.transactions if "楽天モバイル" in t.merchant_raw)
        assert mobile.amount == 864
        assert mobile.installment == {"total_times": 48, "total_amount": 41487}

    def test_refund_is_income(self):
        result, _, _ = parse_csv(SMBC_CARD_CSV, "202509.csv")
        amazon = next(t for t in result.transactions if "AMAZON" in t.merchant_raw.upper() or "ＡＭＡＺＯＮ" in t.merchant_raw)
        assert amazon.direction == "income" and amazon.amount == 5375


class TestSmbcBank:
    def test_two_column_amounts_and_balance(self):
        result, _, _ = parse_csv(SMBC_BANK_CSV, "meisai.csv")
        kept = [t for t in result.transactions if not t.excluded]
        assert [(t.amount, t.direction, t.balance_after) for t in kept] == [
            (2402, "income", 50073),
            (41208, "expense", 47671),
            (25980, "expense", 88879),
            (30000, "income", 114859),
            (231685, "income", 84859),
            (68000, "expense", -146826),
        ]
        assert result.detected_balance == 50073

    def test_placeholder_row_excluded(self):
        """导出末尾的「2024/3/30,,0,"　",0」占位行不是交易。"""
        result, _, _ = parse_csv(SMBC_BANK_CSV, "meisai.csv")
        excluded = [t for t in result.transactions if t.excluded]
        assert len(excluded) == 1 and excluded[0].exclude_reason == "no_amount"

    def test_unpadded_dates(self):
        result, _, _ = parse_csv(SMBC_BANK_CSV, "meisai.csv")
        kept = [t for t in result.transactions if not t.excluded]
        assert kept[0].date == dt.date(2026, 9, 7)
        assert kept[1].date == dt.date(2026, 9, 1)


class TestGenericMapping:
    def test_auto_mapping(self):
        result, det, _ = parse_csv(GENERIC_CSV, "unknown.csv")
        assert det.profile is None
        kept = [t for t in result.transactions if not t.excluded]
        assert [(t.merchant_raw, t.amount, t.direction, t.balance_after) for t in kept] == [
            ("ローソン", 500, "expense", 10000),
            ("給与", 250000, "income", 260000),
        ]

    def test_override_mapping_single_signed_column(self):
        csv_bytes = "date,desc,amt\n2026-09-01,ローソン,-500\n2026-09-02,給与,250000\n".encode("utf-8")
        mapping = ColumnMapping(date=0, merchant=1, amount=2, positive_is_expense=False)
        result, _, _ = parse_csv(csv_bytes, "x.csv", mapping_override=mapping)
        kept = [t for t in result.transactions if not t.excluded]
        assert [(t.amount, t.direction) for t in kept] == [(500, "expense"), (250000, "income")]

    def test_unknown_format_reports_warning(self):
        result, det, _ = parse_csv(b"foo,bar\n1,2\n", "x.csv")
        assert det.mapping is None
        assert "csv:unknown_format" in result.warnings
        assert result.transactions == []


# 楽天カード e-NAVI：UTF-8 BOM，第 8 / 10 列标题含月份，ETC 与分期各带一行补充信息
RAKUTEN_CSV = (
    "\ufeff\"利用日\",\"利用店名・商品名\",\"利用者\",\"支払方法\",\"利用金額\",\"手数料/利息\",\"支払総額\",\"6月支払金額\",\"当月請求額\",\"7月繰越残高\",\"新規サイン\"\r\n"
    "\"2026/05/20\",\"楽天トラベル　国内宿泊\",\"本人\",\"1回払い\",\"5500\",\"0\",\"5500\",\"5500\",\"5500\",\"0\",\"*\"\r\n"
    "\"2026/04/30\",\"ＥＴＣカード売上\",\"ETC\",\"1回払い\",\"100\",\"0\",\"100\",\"100\",\"100\",\"0\",\"*\"\r\n"
    "\"\",\"ｵｵｿﾞｳ      ｵｵｿﾞｳ\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\"\r\n"
    "\"2026/04/30\",\"ＥＴＣカード売上\",\"ETC\",\"1回払い\",\"100\",\"0\",\"100\",\"100\",\"100\",\"0\",\"*\"\r\n"
    "\"\",\"ﾔﾅｷﾞﾀﾆ     ﾔﾅｷﾞﾀﾆ\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\"\r\n"
    "\"2026/04/12\",\"ＡＭＡＺＯＮ．ＣＯ．ＪＰ\",\"本人\",\"1回払い\",\"-1200\",\"0\",\"-1200\",\"-1200\",\"-1200\",\"0\",\"\"\r\n"
    "\"2025/03/27\",\"楽天モバイル製品代\",\"本人\",\"分割48回払い(14回目)\",\"-\",\"0\",\"41487\",\"864\",\"864\",\"29376\",\"\"\r\n"
    "\"\",\"ご利用金額：\41487\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\"\r\n"
).encode("utf-8")

# 2026/06 以前的 e-NAVI 没有「当月請求額」列（10 列）：第 9 列是繰越残高
RAKUTEN_CSV_10COL = (
    "\ufeff\"利用日\",\"利用店名・商品名\",\"利用者\",\"支払方法\",\"利用金額\",\"手数料/利息\",\"支払総額\",\"4月支払金額\",\"5月繰越残高\",\"新規サイン\"\r\n"
    "\"2026/03/05\",\"テスト書店\",\"本人\",\"1回払い\",\"1270\",\"0\",\"1270\",\"1270\",\"0\",\"*\"\r\n"
    "\"2025/03/27\",\"楽天モバイル製品代\",\"本人\",\"分割48回払い(12回目)\",\"41487\",\"0\",\"41487\",\"864\",\"31104\",\"\"\r\n"
).encode("utf-8")

# PayPay 取引履歴：UTF-8 BOM，带时间，出金 / 入金分列且未用侧为「-」
PAYPAY_CSV = (
    "\ufeff取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
    "2026/09/17 19:54:36,-,\"10,000\",-,-,-,-,チャージ,PayPay,テスト銀行 *****40,-,-,0001\r\n"
    "2026/09/17 19:54:36,\"4,035\",-,-,-,-,-,請求書払い,大阪ガス,PayPay残高,-,-,0002\r\n"
    "2026/09/15 14:31:57,60,-,-,-,-,-,支払い,一蘭 - 一蘭　立川店,PayPay残高,-,-,0003\r\n"
    "2026/09/14 12:00:00,980,-,-,-,-,-,支払い,テスト書店,PayPayクレジット,-,-,0004\r\n"
    "2026/09/03 10:08:22,-,\"2,000\",-,-,-,-,ポイント、残高の獲得,Yahoo!ショッピング,PayPayポイント,-,-,lp-1\r\n"
    "2026/09/01 04:54:08,\"1,500\",-,-,-,-,-,期間限定ポイントの期限切れ,-,PayPayポイント,-,-,0005\r\n"
    "2026/01/20 22:54:57,\"13,999\",-,-,-,-,-,送った金額,sei,PayPay残高,-,-,0006\r\n"
).encode("utf-8")


class TestRakutenCard:
    def test_detect_and_statement_month(self):
        det = detect(read_rows(decode(RAKUTEN_CSV)[0]), "enavi202606(1371).csv")
        assert det.profile is RAKUTEN_CARD
        assert det.statement_month == dt.date(2026, 6, 1)

    def test_rows_and_etc_continuation(self):
        result, _, enc = parse_csv(RAKUTEN_CSV, "enavi202606(1371).csv")
        assert enc == "utf-8-sig"
        rows = [t for t in result.transactions if not t.excluded]
        assert len(rows) == 5  # 补充信息行并入上一笔，不单独成行
        etc = [t for t in rows if t.merchant_raw.startswith("ＥＴＣ")]
        # 区间并入商家名：同日同额的往返两程指纹不同（附录 A.4.1）
        assert etc[0].merchant_raw == "ＥＴＣカード売上 ｵｵｿﾞｳ ｵｵｿﾞｳ"
        assert etc[1].merchant_raw == "ＥＴＣカード売上 ﾔﾅｷﾞﾀﾆ ﾔﾅｷﾞﾀﾆ"

    def test_refund_is_income(self):
        result, _, _ = parse_csv(RAKUTEN_CSV, "enavi202606(1371).csv")
        amazon = next(t for t in result.transactions if "ＡＭＡＺＯＮ" in t.merchant_raw)
        assert amazon.direction == "income" and amazon.amount == 1200

    def test_installment_uses_this_month_and_total_from_continuation(self):
        result, _, _ = parse_csv(RAKUTEN_CSV, "enavi202606(1371).csv")
        mobile = next(t for t in result.transactions if "楽天モバイル" in t.merchant_raw)
        assert mobile.amount == 864
        assert mobile.installment == {"total_times": 48, "current_time": 14, "total_amount": 41487}


    def test_installment_dated_in_payment_month(self):
        # 每期记在支払月：不然 48 期全压在 2025/03/27，且同额的各期指纹相同会被判重
        result, _, _ = parse_csv(RAKUTEN_CSV, "enavi202606(1371).csv")
        mobile = next(t for t in result.transactions if "楽天モバイル" in t.merchant_raw)
        assert mobile.date == dt.date(2026, 6, 27)
        amazon = next(t for t in result.transactions if "ＡＭＡＺＯＮ" in t.merchant_raw)
        assert amazon.date == dt.date(2026, 4, 12)  # 普通消费保持利用日

    def test_ten_column_file_reads_payment_not_carryover(self):
        result, _, _ = parse_csv(RAKUTEN_CSV_10COL, "enavi202604(1371).csv")
        book = next(t for t in result.transactions if t.merchant_raw == "テスト書店")
        assert book.amount == 1270  # 不是繰越残高的 0
        mobile = next(t for t in result.transactions if "楽天モバイル" in t.merchant_raw)
        assert mobile.amount == 864  # 不是剩余本金 31104
        assert mobile.date == dt.date(2026, 4, 27)
        assert mobile.installment["current_time"] == 12


class TestPayPay:
    def test_detect_by_column_names(self):
        det = detect(read_rows(decode(PAYPAY_CSV)[0]), "Transactions_20260101-20260917.csv")
        assert det.profile is PAYPAY

    def test_rows(self):
        result, _, _ = parse_csv(PAYPAY_CSV, "Transactions_20260101-20260917.csv")
        by = {t.raw_text.split(",")[-1]: t for t in result.transactions}
        charge = by["0001"]
        assert charge.direction == "income" and charge.amount == 10000
        assert charge.merchant_raw == "チャージ テスト銀行 *****40"
        assert charge.time == dt.time(19, 54, 36)
        gas = by["0002"]
        assert gas.direction == "expense" and gas.amount == 4035 and gas.merchant_raw == "大阪ガス"
        assert by["0003"].merchant_raw == "一蘭 - 一蘭　立川店"

    def test_card_backed_payment_excluded(self):
        # PayPayクレジット 付款不动余额，会出现在信用卡账单里，这里排除以免双计
        result, _, _ = parse_csv(PAYPAY_CSV, "Transactions_20260101-20260917.csv")
        card = next(t for t in result.transactions if "テスト書店" in t.merchant_raw)
        assert card.excluded and card.exclude_reason == "paid_by_card"

    def test_points_and_p2p_get_readable_merchants(self):
        result, _, _ = parse_csv(PAYPAY_CSV, "Transactions_20260101-20260917.csv")
        names = {t.merchant_raw for t in result.transactions}
        assert "ポイント獲得 Yahoo!ショッピング" in names
        assert "ポイント期限切れ" in names
        assert "送金 sei" in names
