"""预算（F7）：默认预算、特别预算、月末预测。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.budgets import Forecast, allocate, fold_days, forecast, judge


def _month(n: int, **days: int) -> list[int]:
    """逐日支出：_month(30, d27=68000, d5=1000)"""
    out = [0] * n
    for k, v in days.items():
        out[int(k[1:]) - 1] += v
    return out


def _flat(n: int, per_day: int, **extra: int) -> list[int]:
    out = [per_day] * n
    for k, v in extra.items():
        out[int(k[1:]) - 1] += v
    return out


# --------------------------------------------------------------------------
# 纯计算
# --------------------------------------------------------------------------


class TestForecast:
    def test_same_habit_projects_historical_total_with_rent_jump(self):
        hist = [_flat(30, 2000, d27=68000) for _ in range(3)]
        now = _flat(30, 2000)
        fc = forecast(30, 10, now, now, hist)
        assert fc.spent == 20000
        assert fc.projected == 30 * 2000 + 68000
        assert fc.pace_ratio == pytest.approx(1.0)
        # 预测路径沿用往常形状：房租那天跳一下
        assert fc.path[26] - fc.path[25] == 2000 + 68000
        assert len(fc.path) == 30 and fc.path[-1] == fc.projected

    def test_faster_pace_raises_projection_but_damped_early(self):
        hist = [_flat(30, 2000) for _ in range(3)]
        fast = _flat(30, 4000)
        fc = forecast(30, 10, fast, fast, hist)
        assert fc.pace_ratio == pytest.approx(2.0)
        # 倍数按已过比例收敛：1 + (2-1)×10/30
        factor = 1 + 10 / 30
        assert fc.projected == round(40000 + 20 * 2000 * factor)

    def test_flagged_one_off_counts_as_spent_but_not_as_habit(self):
        hist = [_flat(30, 2000) for _ in range(3)]
        actual = _flat(30, 2000, d3=300000)  # 换了台电脑
        habitual = _flat(30, 2000)
        fc = forecast(30, 10, actual, habitual, hist)
        assert fc.spent == 320000
        assert fc.pace_ratio == pytest.approx(1.0)
        assert fc.projected == 320000 + 20 * 2000

    def test_range_from_history_spread(self):
        hist = [_flat(30, 1000), _flat(30, 2000), _flat(30, 3000), _flat(30, 4000)]
        now = _flat(30, 2500)
        fc = forecast(30, 15, now, now, hist)
        assert fc.low < fc.projected < fc.high

    def test_no_history_is_linear(self):
        now = _flat(30, 1000)
        fc = forecast(30, 10, now, now, [])
        assert fc.projected == 30000 and fc.low == fc.high == 30000 and fc.basis_months == 0

    def test_finished_month_is_actual(self):
        now = _flat(31, 1000)
        fc = forecast(31, 31, now, now, [_flat(31, 5000)])
        assert fc.projected == fc.spent == 31000

    def test_future_month_is_historical_mean(self):
        fc = forecast(30, 0, [0] * 30, [0] * 30, [_flat(30, 1000), _flat(30, 3000)])
        assert fc.spent == 0 and fc.projected == 60000

    def test_fold_days_keeps_calendar_day(self):
        # 31 日的月份对到 30 天：第 27 天仍是第 27 天，31 日并到月末
        folded = fold_days(_month(31, d27=5, d31=7), 30)
        assert folded[26] == 5 and folded[29] == 7
        feb = fold_days(_month(31, d30=1, d31=2), 28)
        assert feb[27] == 3


class TestJudge:
    def _fc(self, spent, projected, low=None, high=None):
        return Forecast(spent, projected, low or projected, high or projected, None, 3)

    @pytest.mark.parametrize(
        "spent,projected,low,high,expected",
        [
            (110, 150, 140, 160, "over"),
            (50, 150, 120, 180, "will_exceed"),
            (50, 110, 90, 130, "likely_exceed"),
            (50, 90, 80, 105, "at_risk"),
            (85, 95, 90, 99, "at_risk"),  # 已用超过 80%
            (30, 80, 70, 90, "on_track"),
        ],
    )
    def test_levels(self, spent, projected, low, high, expected):
        assert judge(100, spent, self._fc(spent, projected, low, high), 80, finished=False) == expected

    def test_no_budget(self):
        assert judge(None, 1, self._fc(1, 1), 80, finished=False) == "none"

    def test_finished_month_under_budget_is_on_track(self):
        assert judge(100, 90, self._fc(90, 90), 80, finished=True) == "on_track"


class TestAllocate:
    def test_golden_week_spans_two_months(self):
        f, t = dt.date(2026, 4, 29), dt.date(2026, 5, 5)
        april = allocate(70000, f, t, dt.date(2026, 4, 1), dt.date(2026, 5, 1))
        may = allocate(70000, f, t, dt.date(2026, 5, 1), dt.date(2026, 6, 1))
        assert (april, may) == (20000, 50000)

    def test_outside_month_is_zero(self):
        assert allocate(1000, dt.date(2026, 1, 1), dt.date(2026, 1, 3), dt.date(2026, 2, 1), dt.date(2026, 3, 1)) == 0


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def _cat(client, key):
    def walk(nodes):
        for n in nodes:
            if n["key"] == key:
                return n["id"]
            found = walk(n["children"])
            if found:
                return found
        return None

    return walk(client.get("/api/categories").json())


def _spend(client, account, date, amount, category=None, flagged=False, direction="expense"):
    res = client.post("/api/transactions", json={
        "account_id": account, "date": date, "direction": direction, "amount": amount,
        "merchant_raw": "テスト", "category_id": category, "exclude_from_analysis": flagged,
    })
    assert res.status_code == 201, res.text


@pytest.fixture()
def history(auth_client, accounts):
    """6–8 月：每月 1 日起每 3 天 3,000 円外食，27 日房租 68,000。"""
    dining = _cat(auth_client, "food.dining")
    for m in ("06", "07", "08"):
        for day in range(1, 29, 3):
            _spend(auth_client, accounts["card"], f"2026-{m}-{day:02d}", 3000, dining)
        _spend(auth_client, accounts["bank"], f"2026-{m}-27", 68000)
    return {"dining": dining, "food": _cat(auth_client, "food")}


def _status(client, ym="2026-09", as_of="2026-09-10"):
    res = client.get(f"/api/budgets/status?year_month={ym}&as_of={as_of}")
    assert res.status_code == 200, res.text
    return res.json()


class TestBudgetApi:
    def test_default_budget_upsert_and_list(self, auth_client, history):
        a = auth_client.put("/api/budgets/default", json={"amount": 100000}).json()
        b = auth_client.put("/api/budgets/default", json={"amount": 120000}).json()
        assert a["id"] == b["id"] and b["amount"] == 120000
        auth_client.put("/api/budgets/default", json={"category_id": history["food"], "amount": 30000})
        listed = auth_client.get("/api/budgets").json()["defaults"]
        assert [x["category_id"] for x in listed] == [None, history["food"]]
        assert listed[1]["name"] and listed[1]["icon"]

    def test_income_category_rejected(self, auth_client, accounts):
        salary = _cat(auth_client, "income.salary")
        res = auth_client.put("/api/budgets/default", json={"category_id": salary, "amount": 1})
        assert res.status_code == 400

    def test_status_forecasts_on_same_habit(self, auth_client, accounts, history):
        auth_client.put("/api/budgets/default", json={"amount": 100000})
        for day in (1, 4, 7, 10):
            _spend(auth_client, accounts["card"], f"2026-09-{day:02d}", 3000, history["dining"])
        s = _status(auth_client)
        assert s["basis_months"] == 3 and s["elapsed_days"] == 10
        t = s["total"]
        assert t["spent"] == 12000
        # 余下：外食 13,16,19,22,25,28 日六次 + 房租
        assert t["projected"] == 12000 + 6 * 3000 + 68000
        assert t["status"] == "on_track"
        assert t["daily_allowance"] == (100000 - 12000) // 20
        assert len(t["path"]) == 30

    def test_overspending_pace_is_flagged(self, auth_client, accounts, history):
        auth_client.put("/api/budgets/default", json={"amount": 100000})
        for day in range(1, 11):
            _spend(auth_client, accounts["card"], f"2026-09-{day:02d}", 3000, history["dining"])
        t = _status(auth_client)["total"]
        assert t["pace_ratio"] > 1.5
        assert t["status"] in ("likely_exceed", "will_exceed")
        assert t["cut_per_day"] > 0

    def test_category_budget_includes_children(self, auth_client, accounts, history):
        auth_client.put("/api/budgets/default", json={"category_id": history["food"], "amount": 20000})
        _spend(auth_client, accounts["card"], "2026-09-02", 5000, history["dining"])
        cats = _status(auth_client)["categories"]
        food = next(c for c in cats if c["category_id"] == history["food"])
        assert food["spent"] == 5000
        assert food["projected"] > food["spent"]

    def test_special_budget_raises_month_and_tracks_spend(self, auth_client, accounts, history):
        auth_client.put("/api/budgets/default", json={"amount": 100000})
        res = auth_client.post("/api/budgets/special", json={
            "name": "シルバーウィーク", "kind": "holiday", "amount": 50000,
            "date_from": "2026-09-19", "date_to": "2026-09-23",
        })
        assert res.status_code == 201, res.text
        _spend(auth_client, accounts["card"], "2026-09-20", 18000)
        s = _status(auth_client, as_of="2026-09-21")
        assert s["total"]["budget"] == 150000
        assert s["total"]["base"] == 100000 and s["total"]["special_extra"] == 50000
        sp = s["specials"][0]
        assert sp["spent"] == 18000 and sp["allocated"] == 50000 and sp["state"] == "active"

    def test_special_budget_validation_and_patch(self, auth_client, history):
        bad = auth_client.post("/api/budgets/special", json={
            "name": "x", "amount": 1, "date_from": "2026-09-10", "date_to": "2026-09-01",
        })
        assert bad.status_code == 422
        sp = auth_client.post("/api/budgets/special", json={
            "name": "ボーナス", "kind": "bonus", "amount": 30000,
            "date_from": "2026-12-01", "date_to": "2026-12-31", "category_id": history["food"],
        }).json()
        assert sp["category_name"]
        patched = auth_client.patch(f"/api/budgets/special/{sp['id']}", json={"amount": 40000, "clear_category": True}).json()
        assert patched["amount"] == 40000 and patched["category_id"] is None
        assert auth_client.delete(f"/api/budgets/special/{sp['id']}").status_code == 204

    def test_flagged_one_off_counts_in_spent(self, auth_client, accounts, history):
        auth_client.put("/api/budgets/default", json={"amount": 100000})
        _spend(auth_client, accounts["card"], "2026-09-03", 200000, flagged=True)
        t = _status(auth_client)["total"]
        assert t["spent"] == 200000 and t["flagged_spent"] == 200000
        assert t["status"] == "over"
        assert t["pace_ratio"] == pytest.approx(0.0)

    def test_history_of_budget_vs_actual(self, auth_client, history):
        auth_client.put("/api/budgets/default", json={"amount": 100000})
        hist = _status(auth_client)["history"]
        assert [h["year_month"] for h in hist] == ["2026-06", "2026-07", "2026-08"]
        assert all(h["spent"] == 10 * 3000 + 68000 for h in hist)

    def test_suggest_uses_median_and_skips_flagged(self, auth_client, accounts, history):
        _spend(auth_client, accounts["card"], "2026-07-15", 500000, history["dining"], flagged=True)
        s = auth_client.get("/api/budgets/suggest?as_of=2026-09-10").json()
        assert s["basis_months"] == 3
        food = next(c for c in s["categories"] if c["category_id"] == history["food"])
        assert food["amount"] == 30000
        assert s["total"] == 100000  # 98,000 → 向上取整到 5,000

    def test_first_partial_month_not_used_as_history(self, auth_client, accounts):
        _spend(auth_client, accounts["card"], "2026-08-20", 1000)
        _spend(auth_client, accounts["card"], "2026-09-02", 1000)
        assert _status(auth_client)["basis_months"] == 0


class TestInputValidation:
    @pytest.mark.parametrize("url", [
        "/api/summary?year_month=2026-13",
        "/api/reports/overview?year_month=2026-00",
        "/api/budgets/status?year_month=2026-13",
    ])
    def test_bad_month_is_422_not_500(self, auth_client, url):
        assert auth_client.get(url).status_code == 422
