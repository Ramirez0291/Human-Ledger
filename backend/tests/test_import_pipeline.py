"""导入管道端到端：文本 → 待确认区 → 确认入账。

覆盖需求书 F4（三层去重）、F5（分类判别链）、F3.4（待确认区）、附录 A.4 的基准用例。
"""

from __future__ import annotations

from tests.test_parsing import OLIVE_OCT, PAYPAY, RAKUTEN_2, SMBC_BANK


def _import(client, account_id, text, **extra):
    res = client.post("/api/imports/text", json={"account_id": account_id, "text": text, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _kept(detail):
    return [r for r in detail["rows"] if not r["excluded"]]


def _cat_id(client, key):
    def walk(nodes):
        for n in nodes:
            if n["key"] == key:
                return n["id"]
            found = walk(n["children"])
            if found:
                return found
        return None

    return walk(client.get("/api/categories").json())


class TestStaging:
    def test_text_import_creates_draft_batch(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        assert d["batch"]["status"] == "draft"
        kept = _kept(d)
        assert [(r["merchant_raw"], r["amount"]) for r in kept] == [
            ("ライフ此花伝法店", 842),
            ("ミニストップ 日本橋3丁目交差点東店", 230),
            ("ミニストップ 日本橋3丁目交差点東店", 230),
            ("関西電力電気2026/09", 200),
        ]
        # 汇总行被排除但仍在列表里，附带原因
        excluded = [r for r in d["rows"] if r["excluded"]]
        assert any(r["exclude_reason"] == "summary_row" for r in excluded)
        # 全部默认勾选
        assert all(r["is_selected"] for r in kept)

    def test_dictionary_categorizes_known_merchants(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        by_merchant = {r["merchant_raw"]: r for r in _kept(d)}
        assert by_merchant["ライフ此花伝法店"]["category_source"] == "dictionary"
        assert by_merchant["ライフ此花伝法店"]["category_id"] == _cat_id(auth_client, "food.groceries")
        assert by_merchant["関西電力電気2026/09"]["category_id"] == _cat_id(auth_client, "utilities.electricity")

    def test_failed_payment_lands_excluded_with_reason(self, auth_client, accounts):
        d = _import(auth_client, accounts["paypay"], PAYPAY)
        failed = [r for r in d["rows"] if r["exclude_reason"] == "payment_failed"]
        assert len(failed) == 1 and failed[0]["amount"] == 1000
        assert not failed[0]["is_selected"]

    def test_transfer_hint_on_card_payment(self, auth_client, accounts):
        """三井住友銀行流水里的「ラクテンカードサービス」应被提示为转账。"""
        d = _import(auth_client, accounts["bank"], SMBC_BANK)
        row = next(r for r in _kept(d) if "ラクテンカード" in r["merchant_raw"])
        assert row["transfer_hint"] is True
        # 年金则不是转账，而是税金・社会保険
        pension = next(r for r in _kept(d) if "シヤカイホケン" in r["merchant_raw"])
        assert pension["transfer_hint"] is False
        assert pension["category_id"] == _cat_id(auth_client, "tax.pension")

    def test_bank_direction_from_sign(self, auth_client, accounts):
        d = _import(auth_client, accounts["bank"], SMBC_BANK)
        dirs = [(r["amount"], r["direction"]) for r in _kept(d)]
        assert (2402, "income") in dirs
        assert (41208, "expense") in dirs


class TestBatchDedup:
    def test_overlapping_screens_merge(self, auth_client, accounts):
        """L2（附录 A.4.3）：滚动截图的重叠部分在同一批次里合并为一条，可展开。"""
        screen_a = """
JCB ヒラメテイ
2026/08/14 1回払い
¥ 4,994
ETCカード売上 ヒガシオオサカイリ テンポウザンシ
2026/08/02 1回払い
¥ 790
ETCカード売上 ワンガンマイシマ　ヒガシオオサ
2026/08/02 1回払い
¥ 840
"""
        screen_b = """
ETCカード売上 ヒガシオオサカイリ テンポウザンシ
2026/08/02 1回払い
¥ 790
ETCカード売上 ワンガンマイシマ　ヒガシオオサ
2026/08/02 1回払い
¥ 840
ETCカード売上 シマヤ　　　モリシヨウジデ
2026/07/26 1回払い
¥ 770
"""
        first = _import(auth_client, accounts["card"], screen_a)
        batch_id = first["batch"]["id"]
        second = _import(auth_client, accounts["card"], screen_b, batch_id=batch_id)

        kept = _kept(second)
        amounts = sorted(r["amount"] for r in kept)
        assert amounts == [770, 790, 840, 4994], "重叠的两条应只保留一份"
        merged = [r for r in second["rows"] if r["exclude_reason"] == "merged"]
        assert len(merged) == 2

    def test_etc_round_trip_not_merged(self, auth_client, accounts):
        """附录 A.4.1：同日同额、词序相反的往返两程绝不能被批内合并。"""
        d = _import(auth_client, accounts["card"], RAKUTEN_2)
        etc620 = [r for r in _kept(d) if r["amount"] == 620]
        assert len(etc620) == 2
        assert all(r["dup_status"] == "none" for r in etc620)

    def test_expand_restores_merged_rows(self, auth_client, accounts):
        text = """
ローソン 500円
26.09.01
ローソン 500円
26.09.01
"""
        d = _import(auth_client, accounts["cash"], text)
        survivor = next(r for r in d["rows"] if r["dup_status"] == "merged")
        assert survivor["merged_count"] == 2

        res = auth_client.post(f"/api/imports/{d['batch']['id']}/rows/{survivor['id']}/expand")
        assert res.status_code == 200
        detail = auth_client.get(f"/api/imports/{d['batch']['id']}").json()
        assert len(_kept(detail)) == 2, "展开后两条都应恢复为独立行"


class TestLedgerDedup:
    def test_exact_duplicate_unselected_not_deleted(self, auth_client, accounts):
        """L3：已入账的交易再次出现 → 标红、默认不勾选，但行仍然存在。"""
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["card"],
                "date": "2026-09-02",
                "direction": "expense",
                "amount": 842,
                "merchant_raw": "ライフ此花伝法店",
            },
        )
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        life = next(r for r in d["rows"] if r["merchant_raw"] == "ライフ此花伝法店")
        assert life["dup_status"] == "duplicate"
        assert life["is_selected"] is False
        assert life["excluded"] is False  # 不删除，用户可勾回来
        assert life["dup_reason"].startswith("exact:")

    def test_fuzzy_match_selected_but_flagged(self, auth_client, accounts):
        """L3b（附录 A.4.2）：日期差一天、同额同商家 → 黄标但默认勾选。

        Olive 样本里 09/01 与 09/02 各一笔 230 円 ミニストップ 是真实的两笔。
        """
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["card"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 230,
                "merchant_raw": "ミニストップ　日本橋３丁目交差点東店",
            },
        )
        text = """
ミニストップ　日本橋３丁目交差点東店
230円
26.09.02
"""
        d = _import(auth_client, accounts["card"], text)
        row = _kept(d)[0]
        assert row["dup_status"] == "maybe"
        assert row["is_selected"] is True
        assert row["dup_reason"].startswith("fuzzy:")

    def test_same_text_twice_flagged_as_previously_imported(self, auth_client, accounts):
        d1 = _import(auth_client, accounts["card"], OLIVE_OCT)
        assert d1["previously_imported"] is False
        auth_client.post(f"/api/imports/{d1['batch']['id']}/confirm")
        d2 = _import(auth_client, accounts["card"], OLIVE_OCT)
        assert d2["previously_imported"] is True
        # 且所有行都被判为库内重复
        assert all(r["dup_status"] == "duplicate" for r in _kept(d2))


class TestConfirm:
    def test_confirm_writes_selected_rows(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        res = auth_client.post(f"/api/imports/{d['batch']['id']}/confirm")
        assert res.status_code == 200
        body = res.json()
        assert body["imported"] == 4
        assert body["skipped_excluded"] >= 1

        page = auth_client.get("/api/transactions?date_from=2026-08-01&date_to=2026-09-30").json()
        assert page["total"] == 4
        assert page["sum_expense"] == 842 + 230 + 230 + 200
        # 来源标记为截图导入
        assert all(t["source"] == "screenshot" for t in page["items"])

    def test_confirm_learns_categories(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        auth_client.post(f"/api/imports/{d['batch']['id']}/confirm")
        s = auth_client.get(
            "/api/transactions/suggest-category", params={"merchant": "ライフ此花伝法店"}
        ).json()
        assert s["category_id"] == _cat_id(auth_client, "food.groceries")

    def test_counterpart_makes_transfer_pair(self, auth_client, accounts):
        """把「ラクテンカードサービス」指定对方账户后，确认时生成转账而非支出。"""
        d = _import(auth_client, accounts["bank"], SMBC_BANK)
        batch_id = d["batch"]["id"]
        row = next(r for r in _kept(d) if "ラクテンカード" in r["merchant_raw"])
        auth_client.patch(
            f"/api/imports/{batch_id}/rows/{row['id']}",
            json={"counterpart_account_id": accounts["card"]},
        )
        body = auth_client.post(f"/api/imports/{batch_id}/confirm").json()
        assert body["transfers"] == 1
        assert body["imported"] == 4

        # 8 月支出为 0：那 25,980 是还款，不是消费
        assert auth_client.get("/api/summary?year_month=2026-08").json()["expense"] == 0
        # 严谨模式：信用卡余额因还款上升 25,980（没有对应的刷卡记录）
        auth_client.patch("/api/preferences", json={"ledger_mode": "strict"})
        card = next(a for a in auth_client.get("/api/accounts").json() if a["id"] == accounts["card"])
        assert card["balance"] == 25980
        # 轻松模式：还的是没导入的旧账单，信用卡最多还到 0
        auth_client.patch("/api/preferences", json={"ledger_mode": "relaxed"})
        card = next(a for a in auth_client.get("/api/accounts").json() if a["id"] == accounts["card"])
        assert card["balance"] == 0

    def test_balance_after_triggers_reconcile(self, auth_client, accounts):
        """附录 A.3.6：逐行残高在确认时自动生成对账快照。"""
        # 期初余额取截图最早一行之前的值：20,692 + 25,980 = 46,672
        auth_client.patch(f"/api/accounts/{accounts['bank']}", json={"opening_balance": 46672})
        d = _import(auth_client, accounts["bank"], SMBC_BANK)
        batch_id = d["batch"]["id"]
        # 信用卡还款指定对方账户，否则会被当成支出
        row = next(r for r in _kept(d) if "ラクテンカード" in r["merchant_raw"])
        auth_client.patch(
            f"/api/imports/{batch_id}/rows/{row['id']}",
            json={"counterpart_account_id": accounts["card"]},
        )
        body = auth_client.post(f"/api/imports/{batch_id}/confirm").json()
        assert body["reconcile"] is not None
        assert body["reconcile"]["actual_balance"] == 50073
        assert body["reconcile"]["diff"] == 0, "截图逐行残高与系统计算应完全一致"

    def test_unselected_rows_not_written(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        batch_id = d["batch"]["id"]
        first = _kept(d)[0]
        auth_client.patch(f"/api/imports/{batch_id}/rows/{first['id']}", json={"is_selected": False})
        body = auth_client.post(f"/api/imports/{batch_id}/confirm").json()
        assert body["imported"] == 3
        assert body["skipped_unselected"] == 1

    def test_discard_draft(self, auth_client, accounts):
        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        assert auth_client.delete(f"/api/imports/{d['batch']['id']}").status_code == 204
        assert auth_client.get(f"/api/imports/{d['batch']['id']}").status_code == 404


class TestRules:
    def test_rule_beats_dictionary(self, auth_client, accounts):
        """用户规则是判别链第 1 层，优先于内置词典。"""
        dining = _cat_id(auth_client, "food.dining")
        res = auth_client.post(
            "/api/rules",
            json={"match_type": "contains", "pattern": "ライフ", "category_id": dining},
        )
        assert res.status_code == 201

        d = _import(auth_client, accounts["card"], OLIVE_OCT)
        life = next(r for r in _kept(d) if r["merchant_raw"] == "ライフ此花伝法店")
        assert life["category_id"] == dining
        assert life["category_source"] == "rule"
        assert life["category_confidence"] == 1.0

    def test_regex_rule(self, auth_client, accounts):
        sub = _cat_id(auth_client, "comm.subscription")
        auth_client.post(
            "/api/rules",
            json={"match_type": "regex", "pattern": r"^spotify", "category_id": sub},
        )
        d = _import(auth_client, accounts["card"], "ＳＰＯＴＩＦＹ　Ｐ４６４２０７４Ａ７ 1,080円\n26.08.30")
        assert _kept(d)[0]["category_id"] == sub

    def test_invalid_regex_rejected(self, auth_client):
        res = auth_client.post(
            "/api/rules",
            json={"match_type": "regex", "pattern": "(", "category_id": _cat_id(auth_client, "food")},
        )
        assert res.status_code == 400


class TestCsvImport:
    def test_preview_detects_profiles(self, auth_client, accounts):
        from tests.test_csv_source import SMBC_BANK_CSV, SMBC_CARD_CSV

        res = auth_client.post(
            "/api/imports/csv/preview",
            files=[
                ("files", ("202509.csv", SMBC_CARD_CSV, "text/csv")),
                ("files", ("meisai.csv", SMBC_BANK_CSV, "text/csv")),
            ],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert [f["profile"] for f in body["files"]] == ["smbc_card", "smbc_bank"]
        assert body["files"][0]["encoding"] == "cp932"
        assert body["files"][0]["statement_month"] == "2025-09"
        assert body["files"][1]["row_count"] == 7
        # 已有信用卡账户 → 推荐它
        assert body["suggested_account_id"] == accounts["card"]

    def test_import_multiple_files_one_batch(self, auth_client, accounts):
        from tests.test_csv_source import SMBC_CARD_CSV

        card_oct = SMBC_CARD_CSV.replace(b"2025/08", b"2025/09")
        res = auth_client.post(
            "/api/imports/csv",
            data={"account_id": accounts["card"]},
            files=[
                ("files", ("202509.csv", SMBC_CARD_CSV, "text/csv")),
                ("files", ("202510.csv", card_oct, "text/csv")),
            ],
        )
        assert res.status_code == 201, res.text
        d = res.json()
        assert d["batch"]["source_type"] == "csv"
        assert d["batch"]["file_count"] == 2
        kept = [r for r in d["rows"] if not r["excluded"]]
        assert len(kept) == 12
        # 两个文件各一行合计行被排除
        assert d["batch"]["excluded_rows"] == 2

    def test_csv_rows_not_merged_within_batch(self, auth_client, accounts):
        """CSV 里相同的两行是真实的两笔（银行不会重复导出），只标黄不合并。"""
        csv_bytes = (
            "年月日,お引出し,お預入れ,お取り扱い内容,残高,メモ,ラベル\r\n"
            '2026/9/1,500,,"ローソン",1000,"",\r\n'
            '2026/9/1,500,,"ローソン",500,"",\r\n'
        ).encode("cp932")
        d = auth_client.post(
            "/api/imports/csv",
            data={"account_id": accounts["bank"]},
            files=[("files", ("m.csv", csv_bytes, "text/csv"))],
        ).json()
        kept = [r for r in d["rows"] if not r["excluded"]]
        assert len(kept) == 2
        assert all(r["dup_status"] == "maybe" and r["is_selected"] for r in kept)

    def test_confirm_csv_marks_source(self, auth_client, accounts):
        from tests.test_csv_source import SMBC_CARD_CSV

        d = auth_client.post(
            "/api/imports/csv",
            data={"account_id": accounts["card"]},
            files=[("files", ("202509.csv", SMBC_CARD_CSV, "text/csv"))],
        ).json()
        body = auth_client.post(f"/api/imports/{d['batch']['id']}/confirm").json()
        assert body["imported"] == 6
        page = auth_client.get("/api/transactions?date_from=2025-08-01&date_to=2025-09-30").json()
        assert all(t["source"] == "csv" for t in page["items"])
        # 退款计入收入，其余为支出
        assert page["sum_income"] == 5375
        assert page["sum_expense"] == 3665 + 226 + 7614 + 864 + 980  # 分期那期记在 9 月

    def test_unknown_format_rejected(self, auth_client, accounts):
        res = auth_client.post(
            "/api/imports/csv",
            data={"account_id": accounts["card"]},
            files=[("files", ("x.csv", b"foo,bar\n1,2\n", "text/csv"))],
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "csv_unknown_format"

    def test_mapping_override(self, auth_client, accounts):
        import json

        csv_bytes = "d,m,a\n2026-09-01,ローソン,500\n".encode("utf-8")
        res = auth_client.post(
            "/api/imports/csv",
            data={
                "account_id": accounts["cash"],
                "mapping": json.dumps({"date": 0, "merchant": 1, "amount": 2, "has_header": True}),
            },
            files=[("files", ("x.csv", csv_bytes, "text/csv"))],
        )
        assert res.status_code == 201, res.text
        kept = [r for r in res.json()["rows"] if not r["excluded"]]
        assert kept[0]["amount"] == 500 and kept[0]["merchant_raw"] == "ローソン"


class TestLedgerDupWithRepeatedFingerprint:
    def test_two_identical_ledger_rows_do_not_crash_import(self, auth_client, accounts):
        """同日同额同店的两笔真实交易入账后（CSV 来源允许），再导入同指纹的行
        必须标「重复」而不是 500。曾因 scalar_one_or_none 假设指纹唯一而崩溃。"""
        for _ in range(2):
            auth_client.post(
                "/api/transactions",
                json={
                    "account_id": accounts["cash"],
                    "date": "2026-09-01",
                    "direction": "expense",
                    "amount": 230,
                    "merchant_raw": "ミニストップ",
                },
            )
        detail = _import(auth_client, accounts["cash"], "09/01\nミニストップ\n230")
        row = detail["rows"][0]
        assert row["dup_status"] == "duplicate"
        assert row["is_selected"] is False


class TestFastCategorization:
    """「简单快速地帮用户分类」的三个机制：批内推类、品牌记忆、方向校验。"""

    def test_category_propagates_to_same_merchant_in_batch(self, auth_client, accounts):
        text = "09/01\n謎の店 A店\n500\n09/02\n謎の店 A店\n600\n09/03\n別の店\n700"
        d = _import(auth_client, accounts["cash"], text)
        batch_id = d["batch"]["id"]
        rows = _kept(d)
        assert all(r["category_id"] is None for r in rows)
        target = next(r for r in rows if r["amount"] == 500)
        dining = _cat_id(auth_client, "food.dining")
        body = auth_client.patch(
            f"/api/imports/{batch_id}/rows/{target['id']}", json={"category_id": dining}
        ).json()
        assert body["row"]["category_id"] == dining and body["row"]["category_confidence"] == 1.0
        # 同商家的另一行被连带改掉，且标为推断（0.9）；不同商家不动
        assert [a["amount"] for a in body["affected"]] == [600]
        assert body["affected"][0]["category_id"] == dining
        assert body["affected"][0]["category_confidence"] == 0.9
        other = next(r for r in auth_client.get(f"/api/imports/{batch_id}").json()["rows"] if r["amount"] == 700)
        assert other["category_id"] is None

    def test_propagation_never_overrides_user_choice(self, auth_client, accounts):
        text = "09/01\n謎の店\n500\n09/02\n謎の店\n600"
        d = _import(auth_client, accounts["cash"], text)
        batch_id = d["batch"]["id"]
        a, b = sorted(_kept(d), key=lambda r: r["amount"])
        cafe, dining = _cat_id(auth_client, "food.cafe"), _cat_id(auth_client, "food.dining")
        auth_client.patch(f"/api/imports/{batch_id}/rows/{b['id']}", json={"category_id": cafe, "apply_to_similar": False})
        body = auth_client.patch(f"/api/imports/{batch_id}/rows/{a['id']}", json={"category_id": dining}).json()
        assert body["affected"] == []  # b 是用户亲手定的，不被 a 的推类覆盖

    def test_brand_memory_covers_other_stores(self, auth_client, accounts):
        """PayPay 的「ブランド - 店舗名」：记住一家分店，其他分店就能预填。"""
        dining = _cat_id(auth_client, "food.dining")
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["paypay"], "date": "2026-09-01", "direction": "expense",
                "amount": 980, "merchant_raw": "架空ラーメン - 架空ラーメン 立川店", "category_id": dining,
            },
        )
        d = _import(auth_client, accounts["paypay"], "09/05\n架空ラーメン - 架空ラーメン 新宿店\n1080")
        row = _kept(d)[0]
        assert row["category_id"] == dining and row["category_source"] == "memory"

    def test_income_row_never_gets_expense_category(self, auth_client, accounts):
        """银行明细「振込 ｺｸﾎｶﾝﾌﾟ」是国保退款：词典的「コクホ→税金」方向不符，不能采用。"""
        d = _import(auth_client, accounts["bank"], "09/07\n振込　ｺｸﾎｶﾝﾌﾟ ｱｻﾋｸ\n12,340 円 +")
        row = _kept(d)[0]
        assert row["direction"] == "income"
        cats = {c["id"]: c for top in auth_client.get("/api/categories").json() for c in [top, *top["children"]]}
        assert row["category_id"] is None or cats[row["category_id"]]["type"] == "income"


class TestTransferLegDedup:
    def test_other_side_of_confirmed_transfer_is_duplicate(self, auth_client, accounts):
        """银行侧的「ﾍﾟｲﾍﾟｲ 20,000」已确认为转账后，PayPay 侧再导入「チャージ 20,000」
        必须判为重复（L3c）——商家名完全不同，L3/L3b 都抓不到。"""
        d = _import(auth_client, accounts["bank"], "09/10\nﾍﾟｲﾍﾟｲ\n20,000")
        batch_id = d["batch"]["id"]
        row = _kept(d)[0]
        assert row["transfer_hint"]
        auth_client.patch(
            f"/api/imports/{batch_id}/rows/{row['id']}", json={"counterpart_account_id": accounts["paypay"]}
        )
        assert auth_client.post(f"/api/imports/{batch_id}/confirm").json()["transfers"] == 1

        d2 = _import(auth_client, accounts["paypay"], "09/10\nチャージ 三井住友銀行 *****40\n20,000 円 +")
        row2 = _kept(d2)[0]
        assert row2["dup_status"] == "duplicate"
        assert row2["dup_reason"].startswith("transfer_leg:")
        assert row2["is_selected"] is False

    def test_dictionary_skips_wrong_side_and_falls_back_to_refund(self, auth_client, accounts):
        """「ポイント獲得 一蘭」先命中餐饮（支出类）但这是收入行，要继续取到「ポイント獲得」；
        「AMAZON.CO.JP」的退款只命中支出类商家，归入「退款」。"""
        d = _import(auth_client, accounts["paypay"], "09/03\nポイント獲得 一蘭\n55 円 +\n09/04\nＡＭＡＺＯＮ．ＣＯ．ＪＰ\n1,200 円 +")
        rows = {r["merchant_raw"]: r for r in _kept(d)}
        assert rows["ポイント獲得 一蘭"]["category_id"] == _cat_id(auth_client, "income.other")
        assert rows["AMAZON.CO.JP"]["category_id"] == _cat_id(auth_client, "income.refund")


class TestCounterpartSuggestion:
    def test_paypay_charge_prefilled_with_bank(self, auth_client, accounts):
        """PayPay 的钱来自银行自动充值：チャージ 行的对方账户应预填为银行，不用手选。"""
        d = _import(auth_client, accounts["paypay"], "09/10\nチャージ 三井住友銀行 *****40\n20,000 円 +")
        row = _kept(d)[0]
        assert row["transfer_hint"] and row["counterpart_account_id"] == accounts["bank"]

    def test_bank_side_prefilled_by_alias_and_type(self, auth_client, accounts):
        """银行明细：「ﾍﾟｲﾍﾟｲ」→ PayPay 账户（片假名别名）；ATM →唯一的现金账户；「ﾗｸﾃﾝｶ-ﾄﾞｻ-ﾋﾞｽ」→ 楽天カード。"""
        d = _import(auth_client, accounts["bank"], "09/10\nﾍﾟｲﾍﾟｲ\n20,000\n09/11\nカード ｾﾌﾞﾝBK0UJD\n30,000\n09/12\nﾗｸﾃﾝｶ-ﾄﾞｻ-ﾋﾞｽ\n25,980")
        by = {r["amount"]: r for r in _kept(d)}
        assert by[20000]["counterpart_account_id"] == accounts["paypay"]
        assert by[30000]["counterpart_account_id"] == accounts["cash"]
        assert by[25980]["counterpart_account_id"] == accounts["card"]

    def test_counterpart_change_propagates_to_same_merchant(self, auth_client, accounts):
        d = _import(auth_client, accounts["bank"], "09/10\nﾍﾟｲﾍﾟｲ\n20,000\n09/20\nﾍﾟｲﾍﾟｲ\n10,000")
        batch_id = d["batch"]["id"]
        a, b = _kept(d)
        body = auth_client.patch(
            f"/api/imports/{batch_id}/rows/{a['id']}", json={"clear_counterpart": True}
        ).json()
        assert body["row"]["counterpart_account_id"] is None
        assert [x["id"] for x in body["affected"]] == [b["id"]]
        assert body["affected"][0]["counterpart_account_id"] is None


class TestRegistration:
    def test_register_creates_isolated_user(self, auth_client, accounts):
        auth_client.post("/api/logout")
        res = auth_client.post(
            "/api/register", json={"username": "second", "password": "password123", "locale": "ja"}
        )
        assert res.status_code == 201, res.text
        # 新用户看不到第一个用户的账户，但有自己的一套类目
        assert auth_client.get("/api/accounts").json() == []
        assert len(auth_client.get("/api/categories").json()) > 0
        assert auth_client.get("/api/status").json()["allow_registration"] is True

    def test_duplicate_username_rejected(self, auth_client):
        res = auth_client.post(
            "/api/register", json={"username": "tester", "password": "password123", "locale": "ja"}
        )
        assert res.status_code == 409 and res.json()["detail"] == "username_taken"


class TestMultiUserIsolation:
    """开放注册后，第二个用户不能碰到第一个用户的任何东西。"""

    def _second(self, client):
        client.post("/api/logout")
        res = client.post("/api/register", json={"username": "second", "password": "password123", "locale": "ja"})
        assert res.status_code == 201, res.text
        return res.json()

    def test_full_backup_is_owner_only(self, auth_client):
        assert auth_client.get("/api/me").json()["is_owner"] is True
        assert auth_client.get("/api/system").json()["is_owner"] is True
        me = self._second(auth_client)
        assert me["is_owner"] is False
        # 整库备份里有所有用户的账目与密码哈希
        assert auth_client.get("/api/backup").status_code == 403
        assert auth_client.get("/api/system").json()["is_owner"] is False

    def test_staged_row_rejects_foreign_category(self, auth_client, accounts):
        foreign = _cat_id(auth_client, "food.dining")
        self._second(auth_client)
        acc = auth_client.post("/api/accounts", json={"name": "B", "type": "cash", "opening_balance": 0}).json()["id"]
        d = _import(auth_client, acc, OLIVE_OCT)
        row = _kept(d)[0]
        res = auth_client.patch(f"/api/imports/{d['batch']['id']}/rows/{row['id']}", json={"category_id": foreign})
        assert res.status_code == 404
        res = auth_client.post(f"/api/imports/{d['batch']['id']}/bulk", json={"row_ids": [row["id"]], "category_id": foreign})
        assert res.status_code == 404
