"""导入记录：确认时二次判重、放错账户的文件自动改道、整批撤销、只删重叠、收支改记转账。

这些都来自同一类真实事故：同一份明细被导入两次（两个草稿同时开着 / 选错账户），
信用卡还款被记成支出——月度报表的最大支出永远是「信用卡还款」。
"""

from __future__ import annotations

from tests.test_csv_source import SMBC_BANK_CSV, SMBC_CARD_CSV


def _csv(client, account_id, name, content):
    res = client.post(
        "/api/imports/csv",
        data={"account_id": account_id},
        files=[("files", (name, content, "text/csv"))],
    )
    assert res.status_code == 201, res.text
    return res.json()


def _confirm(client, detail):
    res = client.post(f"/api/imports/{detail['batch']['id']}/confirm")
    assert res.status_code == 200, res.text
    return res.json()


def _txns(client, **params):
    q = "&".join(f"{k}={v}" for k, v in {"page_size": 200, **params}.items())
    return client.get(f"/api/transactions?{q}").json()["items"]


class TestConfirmTimeDedup:
    def test_two_open_drafts_of_same_file_do_not_double_book(self, auth_client, accounts):
        a = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        b = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        first = _confirm(auth_client, a)
        second = _confirm(auth_client, b)
        assert first["imported"] == 6
        # 暂存时互相看不见，确认时再查一次
        assert second["imported"] == 0 and second["skipped_duplicate"] == 6
        assert len(_txns(auth_client, account_id=accounts["card"])) == 6

    def test_rows_existing_at_staging_time_are_users_call(self, auth_client, accounts):
        first = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        _confirm(auth_client, first)
        # 暂存时就判为重复；用户仍然勾选 → 按用户的意思入账
        again = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        for r in again["rows"]:
            if not r["excluded"] and not r["is_selected"]:
                auth_client.patch(
                    f"/api/imports/{again['batch']['id']}/rows/{r['id']}", json={"is_selected": True}
                )
        body = _confirm(auth_client, again)
        assert body["skipped_duplicate"] == 0 and body["imported"] == 6


class TestReroute:
    def test_bank_statement_into_card_account_goes_to_bank(self, auth_client, accounts):
        d = _csv(auth_client, accounts["card"], "meisai.csv", SMBC_BANK_CSV)
        kept = [r for r in d["rows"] if not r["excluded"]]
        assert kept and all(r["account_id"] == accounts["bank"] for r in kept)
        assert any(w.startswith("rerouted|meisai.csv|") for w in d["warnings"])

    def test_mismatch_without_matching_account_warns(self, auth_client, accounts):
        auth_client.patch(f"/api/accounts/{accounts['bank']}", json={"is_archived": True})
        d = _csv(auth_client, accounts["card"], "meisai.csv", SMBC_BANK_CSV)
        assert any(w.startswith("account_mismatch|meisai.csv|") for w in d["warnings"])


class TestRevertAndOverlaps:
    def _double_booked(self, client, accounts):
        """同一份银行明细：一次进银行账户，一次（旧版本）进了卡账户。"""
        bank = _csv(client, accounts["bank"], "meisai.csv", SMBC_BANK_CSV)
        _confirm(client, bank)
        # 模拟旧版本：不改道时的结果——把行挪回卡账户再确认
        wrong = _csv(client, accounts["card"], "meisai.csv", SMBC_BANK_CSV)
        kept = [r["id"] for r in wrong["rows"] if not r["excluded"]]
        res = client.post(f"/api/imports/{wrong['batch']['id']}/bulk", json={
            "row_ids": kept, "account_id": accounts["card"], "is_selected": True,
        })
        assert res.status_code == 200, res.text
        _confirm(client, wrong)
        return bank["batch"]["id"], wrong["batch"]["id"]

    def test_history_reports_overlap_per_batch(self, auth_client, accounts):
        bank_id, wrong_id = self._double_booked(auth_client, accounts)
        batches = {b["id"]: b for b in auth_client.get("/api/imports").json()}
        wrong = batches[wrong_id]
        assert wrong["ledger_rows"] > 0
        assert wrong["overlap_rows"] == wrong["ledger_rows"]
        assert set(wrong["overlaps"]) == {str(bank_id)}
        assert "楽天カード" in wrong["account_names"]
        # 后导入的那份是多出来的；更早的那批只提示、不建议删
        assert wrong["redundant_rows"] == wrong["ledger_rows"]
        assert batches[bank_id]["overlap_rows"] > 0 and batches[bank_id]["redundant_rows"] == 0

    def test_remove_overlaps_on_earlier_batch_removes_nothing(self, auth_client, accounts):
        bank_id, _ = self._double_booked(auth_client, accounts)
        assert auth_client.post(f"/api/imports/{bank_id}/remove-overlaps").json()["removed"] == 0

    def test_revert_moves_rows_to_trash_and_allows_reimport(self, auth_client, accounts):
        _, wrong_id = self._double_booked(auth_client, accounts)
        res = auth_client.post(f"/api/imports/{wrong_id}/revert")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["removed"] > 0 and body["batch"]["status"] == "reverted"
        assert body["batch"]["ledger_rows"] == 0
        # 卡账户里只剩银行那份确认出来的还款转账腿，放错进来的支出 / 收入都走了
        left = _txns(auth_client, account_id=accounts["card"])
        assert left and all(t["direction"] == "transfer_in" for t in left)
        # 撤销后再导入同一文件不再提示「导入过」
        again = _csv(auth_client, accounts["bank"], "meisai.csv", SMBC_BANK_CSV)
        assert again["previously_imported"] is True  # 银行那份仍然有效
        assert auth_client.post(f"/api/imports/{wrong_id}/revert").status_code == 409

    def test_remove_overlaps_keeps_the_other_copy(self, auth_client, accounts):
        bank_id, wrong_id = self._double_booked(auth_client, accounts)
        before = len(_txns(auth_client, account_id=accounts["bank"]))
        body = auth_client.post(f"/api/imports/{wrong_id}/remove-overlaps").json()
        assert body["removed"] > 0 and body["batch"]["overlap_rows"] == 0
        assert len(_txns(auth_client, account_id=accounts["bank"])) == before
        # 另一份不再与谁重叠
        batches = {b["id"]: b for b in auth_client.get("/api/imports").json()}
        assert batches[bank_id]["overlap_rows"] == 0

    def test_revert_takes_both_transfer_legs(self, auth_client, accounts):
        d = _csv(auth_client, accounts["bank"], "meisai.csv", SMBC_BANK_CSV)
        rakuten = next(r for r in d["rows"] if r["merchant_raw"].startswith("ﾗｸﾃﾝ"))
        auth_client.patch(
            f"/api/imports/{d['batch']['id']}/rows/{rakuten['id']}",
            json={"counterpart_account_id": accounts["card"]},
        )
        _confirm(auth_client, d)
        assert len(_txns(auth_client, account_id=accounts["card"])) == 1
        auth_client.post(f"/api/imports/{d['batch']['id']}/revert")
        assert _txns(auth_client, account_id=accounts["card"]) == []


class TestConvertToTransfer:
    def _expense(self, client, accounts, merchant="ﾐﾂｲｽﾐﾄﾓｶ-ﾄﾞ (ｶ", amount=287915):
        res = client.post("/api/transactions", json={
            "account_id": accounts["bank"], "date": "2026-08-26", "direction": "expense",
            "amount": amount, "merchant_raw": merchant,
        })
        assert res.status_code == 201, res.text
        return res.json()

    def test_card_payment_becomes_transfer_and_leaves_report(self, auth_client, accounts):
        txn = self._expense(auth_client, accounts)
        ov = auth_client.get("/api/reports/overview?year_month=2026-08").json()
        assert ov["totals"]["expense"] == 287915

        res = auth_client.post(f"/api/transactions/{txn['id']}/to-transfer", json={"counterpart_account_id": accounts["card"]})
        assert res.status_code == 200, res.text
        legs = res.json()
        assert {l["direction"] for l in legs} == {"transfer_out", "transfer_in"}
        assert {l["account_id"] for l in legs} == {accounts["bank"], accounts["card"]}
        assert legs[0]["memo"] == "ﾐﾂｲｽﾐﾄﾓｶ-ﾄﾞ (ｶ"

        ov = auth_client.get("/api/reports/overview?year_month=2026-08").json()
        assert ov["totals"]["expense"] == 0

    def test_rejects_same_account_and_transfers(self, auth_client, accounts):
        txn = self._expense(auth_client, accounts)
        url = f"/api/transactions/{txn['id']}/to-transfer"
        assert auth_client.post(url, json={"counterpart_account_id": accounts["bank"]}).status_code == 400
        auth_client.post(url, json={"counterpart_account_id": accounts["card"]})
        assert auth_client.post(url, json={"counterpart_account_id": accounts["cash"]}).status_code == 400

    def test_large_expenses_flag_card_payment_with_suggestion(self, auth_client, accounts):
        self._expense(auth_client, accounts)
        self._expense(auth_client, accounts, merchant="焼肉テスト", amount=26466)
        items = auth_client.get("/api/reports/large-expenses?year_month=2026-08").json()["items"]
        pay = next(i for i in items if i["merchant"].startswith("ﾐﾂｲ"))
        assert pay["transfer_like"] is True
        assert pay["suggested_counterpart_id"] == accounts["card"]  # 唯一的信用卡
        food = next(i for i in items if i["merchant"] == "焼肉テスト")
        assert food["transfer_like"] is False and food["suggested_counterpart_id"] is None


class TestStagedRestore:
    def test_restore_excluded_row(self, auth_client, accounts):
        d = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        summary = next(r for r in d["rows"] if r["exclude_reason"] == "summary_row")
        res = auth_client.post(f"/api/imports/{d['batch']['id']}/rows/{summary['id']}/restore")
        assert res.status_code == 200, res.text
        assert res.json()["excluded"] is False


class TestRevertDropsSnapshot:
    def test_auto_snapshot_removed_with_batch(self, auth_client, accounts):
        d = _csv(auth_client, accounts["bank"], "meisai.csv", SMBC_BANK_CSV)
        _confirm(auth_client, d)
        bal = lambda: next(a for a in auth_client.get("/api/accounts").json() if a["id"] == accounts["bank"])["balance"]
        assert bal() == 50073  # 轻松模式以导入时读到的残高为准
        auth_client.post(f"/api/imports/{d['batch']['id']}/revert")
        assert bal() == 0  # 错批次留下的快照不能继续当余额起点


class TestPerFileAccounts:
    def _multi(self, client, pairs, **extra):
        files = [("files", (name, content, "text/csv")) for name, content, _ in pairs]
        data = {"account_ids": [str(acc) for _, _, acc in pairs]}
        return client.post("/api/imports/csv", data=data, files=files, **extra)

    def test_each_file_goes_to_its_own_account(self, auth_client, accounts):
        res = self._multi(auth_client, [
            ("202509.csv", SMBC_CARD_CSV, accounts["card"]),
            ("meisai.csv", SMBC_BANK_CSV, accounts["bank"]),
        ])
        assert res.status_code == 201, res.text
        kept = [r for r in res.json()["rows"] if not r["excluded"]]
        by_account = {r["account_id"] for r in kept if r["merchant_raw"].startswith("ＺＯＺＯ")}
        assert by_account == {accounts["card"]}
        assert any(r["account_id"] == accounts["bank"] for r in kept if "ｱﾏｿﾞﾝ" in r["merchant_raw"])

    def test_explicit_choice_is_respected_with_warning(self, auth_client, accounts):
        res = self._multi(auth_client, [("meisai.csv", SMBC_BANK_CSV, accounts["paypay"])])
        d = res.json()
        assert all(r["account_id"] == accounts["paypay"] for r in d["rows"] if not r["excluded"])
        assert any(w.startswith("account_mismatch|meisai.csv|") for w in d["warnings"])

    def test_count_mismatch_rejected(self, auth_client, accounts):
        res = auth_client.post(
            "/api/imports/csv",
            data={"account_ids": [str(accounts["bank"]), str(accounts["card"])]},
            files=[("files", ("meisai.csv", SMBC_BANK_CSV, "text/csv"))],
        )
        assert res.status_code == 400

    def test_preview_suggests_per_file_and_remembers(self, auth_client, accounts):
        second_card = auth_client.post("/api/accounts", json={"name": "Olive クレジット", "type": "credit_card", "opening_balance": 0}).json()["id"]
        files = [
            ("files", ("202509.csv", SMBC_CARD_CSV, "text/csv")),
            ("files", ("meisai.csv", SMBC_BANK_CSV, "text/csv")),
        ]
        p = auth_client.post("/api/imports/csv/preview", files=files).json()["files"]
        # 卡名「Ｏｌｉｖｅ／クレジット」对上了账户名，而不是第一张信用卡
        assert p[0]["suggested_account_id"] == second_card
        assert p[1]["suggested_account_id"] == accounts["bank"]
        # 用户把三井住友卡的明细放进了楽天カード（比如那张卡其实是这个账户）→ 下次记住
        d = _csv(auth_client, accounts["card"], "202509.csv", SMBC_CARD_CSV)
        _confirm(auth_client, d)
        p = auth_client.post("/api/imports/csv/preview", files=files[:1]).json()["files"]
        assert p[0]["suggested_account_id"] == accounts["card"]
