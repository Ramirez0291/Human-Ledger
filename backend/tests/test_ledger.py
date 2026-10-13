"""记账核心逻辑的测试。

重点覆盖三处最容易出错、且出错后不会报错只会算错的地方：
  1. 转账不得计入收支统计
  2. 删除转账必须两条腿一起删
  3. 余额对账的差额计算
"""

from __future__ import annotations


def _balance(client, account_id: int) -> int:
    accounts = client.get("/api/accounts").json()
    return next(a["balance"] for a in accounts if a["id"] == account_id)


class TestAccounts:
    def test_create_and_list(self, auth_client):
        res = auth_client.post(
            "/api/accounts",
            json={"name": "ゆうちょ銀行", "type": "bank", "opening_balance": 50000},
        )
        assert res.status_code == 201
        assert res.json()["balance"] == 50000

    def test_cannot_delete_account_with_transactions(self, auth_client, accounts):
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["cash"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 500,
                "merchant_raw": "ローソン",
            },
        )
        res = auth_client.delete(f"/api/accounts/{accounts['cash']}")
        assert res.status_code == 409
        assert res.json()["detail"] == "account_has_transactions"


class TestTransactions:
    def test_create_updates_balance(self, auth_client, accounts):
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-01",
                "direction": "income",
                "amount": 250000,
                "merchant_raw": "給与",
            },
        )
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-02",
                "direction": "expense",
                "amount": 85000,
                "merchant_raw": "家賃",
            },
        )
        assert _balance(auth_client, accounts["bank"]) == 165000

    def test_merchant_norm_and_fingerprint_are_derived(self, auth_client, accounts):
        res = auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["card"],
                "date": "2026-08-31",
                "direction": "expense",
                "amount": 3652,
                "merchant_raw": "ＡＮＴＨＲＯＰＩＣ＊　ＣＬＡＵＤＥ　ＳＵ",
            },
        )
        assert res.status_code == 201
        # 全角转半角、去空格、转小写
        assert res.json()["merchant_norm"] == "anthropic*claudesu"

    def test_credit_card_balance_is_negative_debt(self, auth_client, accounts):
        """信用卡刷卡后余额为负，表示未偿还金额。"""
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["card"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 25980,
                "merchant_raw": "テスト",
            },
        )
        assert _balance(auth_client, accounts["card"]) == -25980

    def test_direct_transfer_direction_rejected(self, auth_client, accounts):
        """转账方向不允许经普通录入接口写入，必须成对生成。"""
        res = auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-01",
                "direction": "transfer_out",
                "amount": 30000,
                "merchant_raw": "ATM",
            },
        )
        assert res.status_code == 422


class TestTransfer:
    def test_creates_two_legs(self, auth_client, accounts):
        res = auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-01",
                "amount": 30000,
            },
        )
        assert res.status_code == 201
        legs = res.json()
        assert len(legs) == 2
        assert {legs[0]["direction"], legs[1]["direction"]} == {"transfer_out", "transfer_in"}
        assert legs[0]["transfer_group_id"] == legs[1]["transfer_group_id"]

    def test_atm_withdrawal_moves_money_without_spending(self, auth_client, accounts):
        """ATM 取现：钱从银行到现金，两个账户余额一增一减，总额不变。"""
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-01",
                "direction": "income",
                "amount": 100000,
                "merchant_raw": "給与",
            },
        )
        auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-02",
                "amount": 30000,
            },
        )
        assert _balance(auth_client, accounts["bank"]) == 70000
        assert _balance(auth_client, accounts["cash"]) == 30000

    def test_transfer_excluded_from_monthly_expense(self, auth_client, accounts):
        """核心断言：取现 30,000 不得计入当月支出。

        若把转账计成支出，取现时算一笔、花掉时再算一笔，
        同一笔钱会被统计两次，月度支出凭空翻倍。
        """
        auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-05",
                "amount": 30000,
            },
        )
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["cash"],
                "date": "2026-09-06",
                "direction": "expense",
                "amount": 842,
                "merchant_raw": "ライフ此花伝法店",
            },
        )
        summary = auth_client.get("/api/summary?year_month=2026-09").json()
        assert summary["expense"] == 842, "转账被错误计入了支出"

    def test_credit_card_payment_is_transfer_not_expense(self, auth_client, accounts):
        """信用卡还款是转账。样本中三井住友銀行的「ﾗｸﾃﾝｶｰﾄﾞｻｰﾋﾞｽ 25,980円 −」即此情形。"""
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["card"],
                "date": "2026-08-01",
                "direction": "expense",
                "amount": 25980,
                "merchant_raw": "各種ショッピング",
            },
        )
        auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["card"],
                "date": "2026-09-27",
                "amount": 25980,
            },
        )
        # 8 月刷卡计入支出，9 月还款不计入
        assert auth_client.get("/api/summary?year_month=2026-08").json()["expense"] == 25980
        assert auth_client.get("/api/summary?year_month=2026-09").json()["expense"] == 0
        # 还款后信用卡余额归零
        assert _balance(auth_client, accounts["card"]) == 0

    def test_delete_removes_both_legs(self, auth_client, accounts):
        """只删一条腿会让两个账户的余额同时错，且不会有任何报错。"""
        legs = auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-02",
                "amount": 30000,
            },
        ).json()

        assert auth_client.delete(f"/api/transactions/{legs[0]['id']}").status_code == 204

        assert _balance(auth_client, accounts["bank"]) == 0
        assert _balance(auth_client, accounts["cash"]) == 0
        assert auth_client.get("/api/transactions").json()["total"] == 0

    def test_restore_restores_both_legs(self, auth_client, accounts):
        legs = auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-02",
                "amount": 30000,
            },
        ).json()
        auth_client.delete(f"/api/transactions/{legs[0]['id']}")
        auth_client.post(f"/api/transactions/{legs[0]['id']}/restore")

        assert _balance(auth_client, accounts["cash"]) == 30000
        assert auth_client.get("/api/transactions").json()["total"] == 2

    def test_fee_is_recorded_as_expense(self, auth_client, accounts):
        """海外汇款手续费是真实支出，与转账本金分开记。"""
        res = auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-10",
                "amount": 100000,
                "fee": 800,
            },
        )
        assert len(res.json()) == 3
        assert auth_client.get("/api/summary?year_month=2026-09").json()["expense"] == 800
        # 手续费也从转出账户扣除
        assert _balance(auth_client, accounts["bank"]) == -100800

    def test_cannot_edit_transfer_amount_directly(self, auth_client, accounts):
        legs = auth_client.post(
            "/api/transactions/transfer",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["cash"],
                "date": "2026-09-02",
                "amount": 30000,
            },
        ).json()
        res = auth_client.patch(f"/api/transactions/{legs[0]['id']}", json={"amount": 999})
        assert res.status_code == 400


class TestReconcile:
    def test_diff_zero_when_complete(self, auth_client, accounts):
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-01",
                "direction": "income",
                "amount": 50073,
                "merchant_raw": "振込",
            },
        )
        res = auth_client.post(
            f"/api/accounts/{accounts['bank']}/reconcile",
            json={"date": "2026-09-07", "actual_balance": 50073},
        )
        assert res.json()["diff"] == 0

    def test_diff_reveals_missing_transaction(self, auth_client, accounts):
        """漏记一笔 3,200 円时，对账应报出 3,200 的差额（严谨模式才提示）。"""
        auth_client.patch("/api/preferences", json={"ledger_mode": "strict"})
        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["bank"],
                "date": "2026-09-01",
                "direction": "income",
                "amount": 50000,
                "merchant_raw": "振込",
            },
        )
        res = auth_client.post(
            f"/api/accounts/{accounts['bank']}/reconcile",
            json={"date": "2026-09-07", "actual_balance": 53200},
        )
        body = res.json()
        assert body["computed_balance"] == 50000
        assert body["diff"] == 3200

        # 差额应出现在总览的对账提醒里
        alerts = auth_client.get("/api/summary?year_month=2026-09").json()["reconcile_alerts"]
        assert len(alerts) == 1
        assert alerts[0]["diff"] == 3200


class TestCategoryLearning:
    def test_category_is_remembered_per_merchant(self, auth_client, accounts):
        cats = auth_client.get("/api/categories").json()
        food = next(c for c in cats if c["key"] == "food")
        convenience = next(c for c in food["children"] if c["key"] == "food.convenience")

        auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["cash"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 230,
                "merchant_raw": "ミニストップ　日本橋３丁目交差点東店",
                "category_id": convenience["id"],
            },
        )

        # 下次输入同一商家（哪怕写法略有不同）应能预测出同一类别
        res = auth_client.get(
            "/api/transactions/suggest-category",
            params={"merchant": "ミニストップ 日本橋3丁目交差点東店"},
        )
        body = res.json()
        assert body["category_id"] == convenience["id"]
        assert body["confidence"] > 0.6

    def test_changing_category_overrides_memory(self, auth_client, accounts):
        cats = auth_client.get("/api/categories").json()
        food = next(c for c in cats if c["key"] == "food")
        daily = next(c for c in cats if c["key"] == "daily")

        txn = auth_client.post(
            "/api/transactions",
            json={
                "account_id": accounts["cash"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 500,
                "merchant_raw": "ダイソー",
                "category_id": food["id"],
            },
        ).json()

        auth_client.patch(f"/api/transactions/{txn['id']}", json={"category_id": daily["id"]})

        res = auth_client.get(
            "/api/transactions/suggest-category", params={"merchant": "ダイソー"}
        ).json()
        assert res["category_id"] == daily["id"], "用户的最新意图应覆盖历史记忆"


class TestFiltering:
    def test_filter_by_account_and_search(self, auth_client, accounts):
        for account, merchant, amount in [
            (accounts["cash"], "ローソン", 500),
            (accounts["cash"], "ライフ此花伝法店", 842),
            (accounts["card"], "ローソン", 300),
        ]:
            auth_client.post(
                "/api/transactions",
                json={
                    "account_id": account,
                    "date": "2026-09-01",
                    "direction": "expense",
                    "amount": amount,
                    "merchant_raw": merchant,
                },
            )

        assert auth_client.get(f"/api/transactions?account_id={accounts['cash']}").json()["total"] == 2
        assert auth_client.get("/api/transactions?q=ローソン").json()["total"] == 2

        page = auth_client.get(f"/api/transactions?account_id={accounts['cash']}").json()
        assert page["sum_expense"] == 1342


class TestMerchantAutocomplete:
    def test_matches_halfwidth_input_against_fullwidth_history(self, auth_client, accounts):
        """用户用半角输入时也要能补全出库里全角存储的商家名。

        分类预测走规范化路径、能命中；若补全只匹配原文就会两者行为不一致。
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
        res = auth_client.get(
            "/api/transactions/merchants", params={"q": "ミニストップ 日本橋3丁目"}
        ).json()
        assert "ミニストップ　日本橋３丁目交差点東店" in res


class TestRelaxedMode:
    """轻松模式（默认）：漏记不拖累余额。"""

    def _txn(self, client, account, date, direction, amount):
        res = client.post("/api/transactions", json={
            "account_id": account, "date": date, "direction": direction, "amount": amount, "merchant_raw": "x",
        })
        assert res.status_code == 201, res.text

    def _balances(self, client):
        return {a["id"]: a["balance"] for a in client.get("/api/accounts").json()}

    def test_default_is_relaxed(self, auth_client):
        assert auth_client.get("/api/preferences").json() == {"ledger_mode": "relaxed"}
        assert auth_client.patch("/api/preferences", json={"ledger_mode": "loose"}).status_code == 422

    def test_card_repayments_for_unimported_statements_stop_at_zero(self, auth_client, accounts):
        # 银行明细里半年的还款，卡明细只导入了最近一个月
        for m in ("04", "05", "06", "07"):
            auth_client.post("/api/transactions/transfer", json={
                "from_account_id": accounts["bank"], "to_account_id": accounts["card"],
                "date": f"2026-{m}-27", "amount": 50000,
            })
        self._txn(auth_client, accounts["card"], "2026-07-05", "expense", 30000)
        self._txn(auth_client, accounts["card"], "2026-08-03", "expense", 12000)
        # 7/27 那笔还款付的是 7 月的 30,000（多出的 20,000 是更早的账单）；8 月刷的 12,000 还欠着
        assert self._balances(auth_client)[accounts["card"]] == -12000
        auth_client.patch("/api/preferences", json={"ledger_mode": "strict"})
        assert self._balances(auth_client)[accounts["card"]] == 200000 - 42000

    def test_same_day_repay_then_spend_not_lost(self, auth_client, accounts):
        self._txn(auth_client, accounts["card"], "2026-08-01", "expense", 10000)
        auth_client.post("/api/transactions/transfer", json={
            "from_account_id": accounts["bank"], "to_account_id": accounts["card"],
            "date": "2026-08-27", "amount": 10000,
        })
        self._txn(auth_client, accounts["card"], "2026-08-27", "expense", 3000)
        assert self._balances(auth_client)[accounts["card"]] == -3000

    def test_cash_never_below_zero(self, auth_client, accounts):
        self._txn(auth_client, accounts["cash"], "2026-08-01", "expense", 5000)  # 没记过取现
        assert self._balances(auth_client)[accounts["cash"]] == 0

    def test_latest_real_balance_is_the_starting_point(self, auth_client, accounts):
        self._txn(auth_client, accounts["cash"], "2026-08-01", "expense", 5000)
        res = auth_client.post(f"/api/accounts/{accounts['cash']}/reconcile", json={"date": "2026-09-01", "actual_balance": 20000})
        assert res.status_code in (200, 201), res.text
        self._txn(auth_client, accounts["cash"], "2026-09-02", "expense", 1500)
        self._txn(auth_client, accounts["cash"], "2026-08-15", "expense", 999)  # 快照之前补录的不再影响
        assert self._balances(auth_client)[accounts["cash"]] == 18500
        # 首页不提示差额
        assert auth_client.get("/api/summary?year_month=2026-09").json()["reconcile_alerts"] == []



class TestComplianceTension:
    """合规模式：账面越对不上，紧张度越高；补记之后缓和。"""

    def _strict(self, client):
        client.patch("/api/preferences", json={"ledger_mode": "strict"})

    def _spend(self, client, account, date, amount):
        client.post("/api/transactions", json={
            "account_id": account, "date": date, "direction": "expense", "amount": amount, "merchant_raw": "x",
        })

    def test_relaxed_mode_is_always_calm(self, auth_client, accounts):
        auth_client.post(f"/api/accounts/{accounts['cash']}/reconcile", json={"date": "2026-09-01", "actual_balance": 99999})
        assert auth_client.get("/api/compliance").json()["level"] == 0

    def test_escalates_with_diff_and_calms_after_backfill(self, auth_client, accounts):
        self._strict(auth_client)
        for a in ("bank", "card", "paypay"):
            auth_client.patch(f"/api/accounts/{accounts[a]}", json={"is_archived": True})
        auth_client.post(f"/api/accounts/{accounts['cash']}/reconcile", json={"date": "2026-09-01", "actual_balance": 0})
        assert auth_client.get("/api/compliance").json()["level"] == 0  # 账实相符

        auth_client.post(f"/api/accounts/{accounts['cash']}/reconcile", json={"date": "2026-09-02", "actual_balance": -40000})
        body = auth_client.get("/api/compliance").json()
        assert body["total_abs_diff"] == 40000 and body["level"] == 4  # 4 万 / 保底 5 万 ≥ 30%

        # 补记漏掉的 39,000：差额按现在的流水重算，只剩 1,000
        self._spend(auth_client, accounts["cash"], "2026-09-02", 39000)
        body = auth_client.get("/api/compliance").json()
        assert body["total_abs_diff"] == 1000 and body["level"] == 2

    def test_never_reconciled_account_is_a_gap(self, auth_client, accounts):
        self._strict(auth_client)
        self._spend(auth_client, accounts["cash"], "2026-09-02", 100)
        body = auth_client.get("/api/compliance").json()
        assert body["gaps"] >= 1 and body["level"] == 1
        assert body["accounts"][0]["status"] == "unaudited"
