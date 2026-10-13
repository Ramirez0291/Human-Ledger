"""报表、CSV 导出与备份（需求书 F6 / F9）。

报表出错的典型方式是「算出一个数但算错口径」：转账混进支出、子类没上卷、
筛选大分類时漏掉子类。这些都不会报错，所以逐个用固定数据钉住。
"""

from __future__ import annotations

import io
import sqlite3
import zipfile


def _cat(client, key: str) -> int:
    for top in client.get("/api/categories").json():
        if top["key"] == key:
            return top["id"]
        for ch in top["children"]:
            if ch["key"] == key:
                return ch["id"]
    raise KeyError(key)


def _txn(client, account_id, date, direction, amount, merchant, category_id=None, memo=None):
    res = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "date": date,
            "direction": direction,
            "amount": amount,
            "merchant_raw": merchant,
            "category_id": category_id,
            "memo": memo,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _seed(client, accounts):
    """2026-09：收入 300,000；支出 食 1,500（便利店 1,000 + 外食 500）、住 80,000；
    未分类 200；一笔 ATM 转账；2026-08：支出 3,000。"""
    conv = _cat(client, "food.convenience")
    food_top = _cat(client, "food")
    housing = _cat(client, "housing")
    _txn(client, accounts["bank"], "2026-09-01", "income", 300000, "給与")
    _txn(client, accounts["cash"], "2026-09-02", "expense", 600, "セブン-イレブン", conv)
    _txn(client, accounts["cash"], "2026-09-03", "expense", 400, "セブン－イレブン 1234", conv)
    _txn(client, accounts["card"], "2026-09-04", "expense", 500, "すき家", food_top)
    _txn(client, accounts["bank"], "2026-09-05", "expense", 80000, "家賃", housing)
    _txn(client, accounts["cash"], "2026-09-06", "expense", 200, "謎の店")
    _txn(client, accounts["cash"], "2026-08-20", "expense", 3000, "ドン・キホーテ", conv)
    res = client.post(
        "/api/transactions/transfer",
        json={
            "from_account_id": accounts["bank"],
            "to_account_id": accounts["cash"],
            "date": "2026-09-07",
            "amount": 20000,
            "merchant_raw": "ATM",
        },
    )
    assert res.status_code == 201, res.text
    return {"conv": conv, "food": food_top, "housing": housing}


class TestOverview:
    def test_totals_exclude_transfers_and_compare_previous(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get("/api/reports/overview", params={"year_month": "2026-09"}).json()
        assert body["totals"] == {
            "income": 300000,
            "expense": 81700,
            "net": 218300,
            "count": 6,
        }
        assert body["previous"]["expense"] == 3000

    def test_category_rollup_with_drilldown(self, auth_client, accounts):
        ids = _seed(auth_client, accounts)
        body = auth_client.get("/api/reports/overview", params={"year_month": "2026-09"}).json()
        bd = body["expense_by_category"]
        assert bd["total"] == 81700
        assert bd["uncategorized"] == 200
        assert [i["category_id"] for i in bd["items"]] == [ids["housing"], ids["food"]]

        food = bd["items"][1]
        assert food["amount"] == 1500
        # 直接记在大分類上的 500 与子类的 1,000 分别是两个下钻项
        children = {c["category_id"]: c["amount"] for c in food["children"]}
        assert children == {ids["conv"]: 1000, ids["food"]: 500}
        assert abs(sum(i["share"] for i in bd["items"]) + 200 / 81700 - 1) < 0.001

    def test_top_merchants_merge_store_variants(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get("/api/reports/overview", params={"year_month": "2026-09"}).json()
        tops = body["top_merchants"]
        assert tops[0]["merchant"] == "家賃"
        seven = next(m for m in tops if m["merchant_norm"].startswith("セブン"))
        # 「セブン-イレブン」与「セブン－イレブン 1234」规范化后同店（全角连字符、店番），合并为一行
        assert seven["amount"] == 1000 and seven["count"] == 2

    def test_account_view_includes_transfer_movement(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get("/api/reports/overview", params={"year_month": "2026-09"}).json()
        by_id = {a["id"]: a for a in body["accounts"]}
        bank = by_id[accounts["bank"]]
        assert bank["balance"] == 300000 - 80000 - 20000
        assert bank["month_delta"] == 200000
        assert bank["month_income"] == 300000 and bank["month_expense"] == 80000
        cash = by_id[accounts["cash"]]
        assert cash["month_delta"] == 20000 - 600 - 400 - 200

    def test_filter_by_top_category_includes_children(self, auth_client, accounts):
        ids = _seed(auth_client, accounts)
        body = auth_client.get(
            "/api/reports/overview",
            params={"year_month": "2026-09", "category_id": ids["food"]},
        ).json()
        assert body["totals"]["expense"] == 1500
        sub = auth_client.get(
            "/api/reports/overview",
            params={"year_month": "2026-09", "category_id": ids["conv"]},
        ).json()
        assert sub["totals"]["expense"] == 1000

    def test_filter_by_account_and_keyword(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get(
            "/api/reports/overview",
            params={"year_month": "2026-09", "account_id": accounts["cash"]},
        ).json()
        assert body["totals"]["expense"] == 1200
        body = auth_client.get(
            "/api/reports/overview", params={"year_month": "2026-09", "q": "セブン"}
        ).json()
        assert body["totals"]["expense"] == 1000


class TestTrend:
    def test_fills_empty_months_and_orders_ascending(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get(
            "/api/reports/trend", params={"end": "2026-09", "months": 3}
        ).json()
        months = body["months"]
        assert [m["month"] for m in months] == ["2026-07", "2026-08", "2026-09"]
        zero = {"excluded_expense": 0, "excluded_income": 0}
        assert months[0] == {"month": "2026-07", "income": 0, "expense": 0, "net": 0, **zero}
        assert months[1]["expense"] == 3000
        assert months[2] == {
            "month": "2026-09",
            "income": 300000,
            "expense": 81700,
            "net": 218300,
            **zero,
        }

    def test_year_boundary(self, auth_client, accounts):
        _txn(auth_client, accounts["cash"], "2025-12-31", "expense", 100, "x")
        body = auth_client.get(
            "/api/reports/trend", params={"end": "2026-01", "months": 2}
        ).json()
        assert [m["month"] for m in body["months"]] == ["2025-12", "2026-01"]
        assert body["months"][0]["expense"] == 100


class TestExport:
    def test_csv_has_bom_header_and_localized_categories(self, auth_client, accounts):
        _seed(auth_client, accounts)
        res = auth_client.get("/api/transactions/export.csv", params={"date_from": "2026-09-01"})
        assert res.status_code == 200
        assert res.headers["content-disposition"].startswith("attachment")
        raw = res.content
        assert raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").splitlines()
        assert lines[0].startswith("id,date,time,direction,amount,signed_amount,account,")
        # 9 月：6 笔收支 + 转账 2 条腿
        assert len(lines) == 1 + 8
        seven = next(line for line in lines if "セブン－イレブン 1234" in line)
        cells = seven.split(",")
        assert cells[3] == "expense" and cells[4] == "400" and cells[5] == "-400"
        assert cells[7] == "餐饮食品" and cells[8] == "便利店"
        transfer_in = next(line for line in lines if ",transfer_in," in line)
        assert transfer_in.split(",")[5] == "20000"

    def test_export_respects_filters(self, auth_client, accounts):
        _seed(auth_client, accounts)
        res = auth_client.get(
            "/api/transactions/export.csv",
            params={"account_id": accounts["cash"], "direction": "expense"},
        )
        lines = res.content.decode("utf-8-sig").splitlines()
        assert len(lines) == 1 + 4  # 9 月 3 笔 + 8 月 1 笔

    def test_requires_login(self, client):
        assert client.get("/api/transactions/export.csv").status_code == 401


class TestBackup:
    def test_zip_contains_consistent_db_snapshot(self, auth_client, accounts, tmp_path):
        _seed(auth_client, accounts)
        res = auth_client.get("/api/backup")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            names = zf.namelist()
            assert "ledger.db" in names and "MANIFEST.txt" in names
            db_bytes = zf.read("ledger.db")
        # 快照要能直接打开，并且包含刚写入（可能还只在 WAL 里）的数据
        path = tmp_path / "restored.db"
        path.write_bytes(db_bytes)
        con = sqlite3.connect(path)
        try:
            n = con.execute("select count(*) from transactions").fetchone()[0]
        finally:
            con.close()
        assert n == 9


class TestListCategoryScope:
    def test_list_by_top_category_includes_children(self, auth_client, accounts):
        """报表下钻后跳到流水页，按大分類筛选必须能看到记在子类上的交易。"""
        ids = _seed(auth_client, accounts)
        res = auth_client.get(
            "/api/transactions", params={"category_id": ids["food"], "date_from": "2026-09-01"}
        ).json()
        assert res["total"] == 3 and res["sum_expense"] == 1500
        res = auth_client.get("/api/transactions", params={"category_id": ids["conv"]}).json()
        assert res["total"] == 3  # 含 8 月那笔


class TestExclusions:
    """「主动除外大额 / 意外开支」：标记、阈值、类目三种方式，且被除外的金额要能看见。"""

    def _flag_rent(self, client):
        rows = client.get("/api/transactions", params={"q": "家賃"}).json()["items"]
        res = client.patch(f"/api/transactions/{rows[0]['id']}", json={"exclude_from_analysis": True})
        assert res.status_code == 200 and res.json()["exclude_from_analysis"] is True
        return rows[0]["id"]

    def test_flagged_transaction_left_out_but_reported(self, auth_client, accounts):
        _seed(auth_client, accounts)
        self._flag_rent(auth_client)
        body = auth_client.get("/api/reports/overview", params={"year_month": "2026-09"}).json()
        assert body["totals"]["expense"] == 1700
        assert body["raw_totals"]["expense"] == 81700
        assert body["excluded"] == {"expense": 80000, "income": 0, "count": 1}
        assert all(i["key"] != "housing" for i in body["expense_by_category"]["items"])
        assert all(m["merchant"] != "家賃" for m in body["top_merchants"])
        # 余额不受影响：除外只作用于分析口径
        bank = next(a for a in body["accounts"] if a["id"] == accounts["bank"])
        assert bank["balance"] == 200000

    def test_include_flagged_shows_everything(self, auth_client, accounts):
        _seed(auth_client, accounts)
        self._flag_rent(auth_client)
        body = auth_client.get(
            "/api/reports/overview", params={"year_month": "2026-09", "include_flagged": True}
        ).json()
        assert body["totals"]["expense"] == 81700 and body["excluded"]["count"] == 0

    def test_threshold_only_hits_expenses(self, auth_client, accounts):
        _seed(auth_client, accounts)
        body = auth_client.get(
            "/api/reports/overview", params={"year_month": "2026-09", "max_single": 10000}
        ).json()
        assert body["totals"]["expense"] == 1700
        assert body["totals"]["income"] == 300000  # 大额收入不被阈值拿掉

    def test_exclude_category_includes_children(self, auth_client, accounts):
        ids = _seed(auth_client, accounts)
        body = auth_client.get(
            "/api/reports/overview",
            params={"year_month": "2026-09", "exclude_categories": f"{ids['food']},{ids['housing']}"},
        ).json()
        assert body["totals"]["expense"] == 200  # 只剩未分类的那笔

    def test_trend_and_daily_carry_excluded_amounts(self, auth_client, accounts):
        _seed(auth_client, accounts)
        self._flag_rent(auth_client)
        sep = auth_client.get("/api/reports/trend", params={"end": "2026-09", "months": 2}).json()["months"][1]
        assert sep["expense"] == 1700 and sep["excluded_expense"] == 80000
        daily = auth_client.get("/api/reports/daily", params={"year_month": "2026-09"}).json()
        assert len(daily["days"]) == 30 and len(daily["previous"]) == 31
        d5 = daily["days"][4]
        assert d5 == {"day": 5, "expense": 0, "excluded": 80000}
        assert daily["days"][1]["expense"] == 600
        assert daily["previous"][19]["expense"] == 3000

    def test_large_expenses_lists_top_and_flagged(self, auth_client, accounts):
        _seed(auth_client, accounts)
        rent_id = self._flag_rent(auth_client)
        items = auth_client.get(
            "/api/reports/large-expenses", params={"year_month": "2026-09", "limit": 2, "max_single": 550}
        ).json()["items"]
        assert items[0]["id"] == rent_id and items[0]["exclude_from_analysis"] is True
        assert items[1]["amount"] == 600 and items[1]["over_threshold"] is True
