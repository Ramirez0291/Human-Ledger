"""中国地区包与微信账单导入的测试。

夹具按微信支付账单的**格式**构造（xlsx：说明区 + 列标题 + Excel 序列号日期 + 文本金额；
旧版 CSV：UTF-8、每格后带 Tab），内容为虚构数据。真实账单含昵称与卡号，不进仓库。
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient

from app.regions import CN, JP, get_region
from app.services.importing.csv_source import WECHAT, detect, load_rows, parse_csv
from app.services.importing.payment_methods import method_key, new_account_for
from app.services.importing.xlsx import excel_serial_to_datetime, read_xlsx_rows
from app.services.parsing.amounts import parse_amount

HEADER = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"]


def serial(y: int, mo: int, d: int, hh: int = 12, mm: int = 0) -> float:
    delta = dt.datetime(y, mo, d, hh, mm) - dt.datetime(1899, 12, 30)
    return delta.total_seconds() / 86400


# 一份覆盖各类交易的微信账单：绑卡消费、零钱消费、红包收发、转账、部分退款、提现（含服务费）、充值
WECHAT_ROWS: list[list] = [
    [serial(2026, 9, 3, 11, 32), "商户消费", "麦当劳", "深圳金拱门食品有限公司", "支出", "23.5", "招商银行信用卡(0575)", "支付成功", "4200000001", "2210001", "/"],
    [serial(2026, 9, 3, 12, 0), "商户消费", "喜茶", "喜茶支付中心支付单", "支出", "22", "零钱", "支付成功", "4200000002", "2210002", "/"],
    [serial(2026, 9, 4, 20, 0), "微信红包（单发）", "发给小明", "/", "支出", "66.66", "零钱", "支付成功", "1000000003", "/", "/"],
    [serial(2026, 9, 5, 9, 0), "微信红包", "小明", "/", "收入", "200", "/", "已存入零钱", "1000000004", "/", "/"],
    [serial(2026, 9, 6, 10, 0), "转账", "张三", "转账备注:微信转账", "收入", "10000", "/", "已存入零钱", "1000000005", "/", "/"],
    [serial(2026, 9, 7, 16, 30), "商户消费", "中铁网络", "12306消费", "支出", "75", "零钱", "已退款(¥38.00)", "4200000006", "2210006", "/"],
    [serial(2026, 9, 8, 9, 0), "中铁网络-退款", "中铁网络", "中铁网络", "收入", "38", "零钱", "已退款¥38.00", "5020000007", "/", "/"],
    [serial(2026, 9, 9, 10, 21), "零钱提现", "中国银行(6721)", "/", "/", "5005", "中国银行储蓄卡(6721)", "提现已到账", "1300000008", "/", "服务费¥5.00"],
    [serial(2026, 9, 10, 8, 0), "零钱充值", "中国银行(6721)", "/", "/", "100", "中国银行储蓄卡(6721)", "充值完成", "1300000009", "/", "/"],
    [serial(2026, 9, 11, 8, 0), "商户消费", "某商店", "/", "支出", "10", "零钱", "支付失败", "4200000010", "/", "/"],
    [serial(2026, 9, 12, 12, 0), "商户消费", "啫啫煲（某店）", "美团/大众点评点餐订单-0810471981394832", "支出", "157", "零钱", "支付成功", "4200000011", "/", "/"],
]


def make_xlsx(rows: list[list]) -> bytes:
    """最小 xlsx：字符串走 sharedStrings，数字原样。与微信导出的结构一致（首张表、无公式）。"""
    shared: list[str] = []
    index: dict[str, int] = {}

    def col(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{col(c)}{r}"
            if v is None:
                continue
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                if v not in index:
                    index[v] = len(shared)
                    shared.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{index[v]}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook {ns} {rel_ns}><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        z.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><sst {ns}>' + "".join(f"<si><t>{escape(t)}</t></si>" for t in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


PREAMBLE = [
    ["微信支付账单明细"],
    ["微信昵称：[测试用户]"],
    ["起始时间：[2026-09-01 00:00:00] 终止时间：[2026-09-30 23:59:59]"],
    ["导出类型：[全部账单]"],
    ["共10笔记录"],
    ["----------------------微信支付账单明细列表--------------------"],
]

WECHAT_XLSX = make_xlsx(PREAMBLE + [HEADER] + WECHAT_ROWS)


def wechat_csv(rows: list[list]) -> bytes:
    """旧版导出：UTF-8 BOM 的 CSV，日期是文本，金额带 ¥，每格后跟一个 Tab。"""
    lines = ["微信支付账单明细", "微信昵称：[测试用户]", "", ",".join(HEADER)]
    for row in rows:
        when = excel_serial_to_datetime(str(row[0]))
        cells = [when.strftime("%Y-%m-%d %H:%M:%S")] + [str(c) for c in row[1:]]
        cells[5] = "¥" + cells[5]
        lines.append(",".join(c + "\t" for c in cells))
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# 地区包
# --------------------------------------------------------------------------


class TestRegions:
    def test_registry(self):
        assert get_region("cn") is CN
        assert get_region(None) is JP  # 升级前的用户都是日元账本
        assert CN.minor_unit == 2 and JP.minor_unit == 0

    def test_amounts_in_minor_units(self):
        assert parse_amount("238.9", 2) == 23890
        assert parse_amount("¥23.50", 2) == 2350
        assert parse_amount("￥1,234.56", 2) == 123456
        assert parse_amount("200", 2) == 20000
        assert parse_amount("12.5元", 2) == 1250
        assert parse_amount("/", 2) is None
        # 日元行为不变：带小数的不是日元金额
        assert parse_amount("1,234円") == 1234
        assert parse_amount("0.00") is None


class TestSetupWithRegion:
    def test_cn_user_gets_cn_categories(self, client: TestClient):
        res = client.post(
            "/api/setup",
            json={"username": "cn", "password": "password123", "locale": "zh-CN", "region": "CN"},
        )
        assert res.status_code == 201, res.text
        user = res.json()
        assert user["region"] == "CN"
        assert user["currency"] == "CNY"
        assert user["minor_unit"] == 2

        keys = set()
        for c in client.get("/api/categories").json():
            keys.add(c["key"])
            keys.update(ch["key"] for ch in c.get("children", []))
        assert {"social.redpacket", "income.redpacket", "food.delivery", "finance.fee"} <= keys
        assert "tax.resident" not in keys  # 日本的住民税不出现在中国账本里

    def test_default_region_is_jp(self, client: TestClient):
        res = client.post("/api/setup", json={"username": "jp", "password": "password123"})
        assert res.json()["region"] == "JP"
        assert res.json()["minor_unit"] == 0

    def test_unknown_region_rejected(self, client: TestClient):
        res = client.post("/api/setup", json={"username": "x", "password": "password123", "region": "XX"})
        assert res.status_code == 400
        assert res.json()["detail"] == "unsupported_region"

    def test_status_lists_regions(self, client: TestClient):
        body = client.get("/api/status").json()
        assert set(body["supported_regions"]) == {"JP", "CN"}


# --------------------------------------------------------------------------
# xlsx 与微信解析
# --------------------------------------------------------------------------


class TestXlsx:
    def test_reads_shared_strings_and_numbers(self):
        rows = read_xlsx_rows(make_xlsx([["a", 1.5], ["", "b"], [], ["c"]]))
        assert rows == [["a", "1.5"], ["", "b"], ["c"]]

    def test_excel_serial(self):
        assert excel_serial_to_datetime(str(serial(2026, 9, 3, 11, 32))) == dt.datetime(2026, 9, 3, 11, 32)
        assert excel_serial_to_datetime("麦当劳") is None


class TestWechatParse:
    @pytest.fixture(params=["xlsx", "csv"])
    def parsed(self, request):
        content = WECHAT_XLSX if request.param == "xlsx" else wechat_csv(WECHAT_ROWS)
        result, det, _ = parse_csv(content, "微信支付账单.xlsx")
        assert det.profile is WECHAT
        return result.transactions

    def test_long_csv_with_trailing_tabs_stays_comma_separated(self):
        """旧版 CSV 每格后跟 Tab：行一多 Tab 比逗号多，不能因此当成 TSV。"""
        result, det, _ = parse_csv(wechat_csv(WECHAT_ROWS * 6), "wechat.csv")
        assert det.profile is WECHAT
        assert len([t for t in result.transactions if t.merchant_raw == "麦当劳"]) == 6

    def test_detect_skips_preamble(self):
        rows, enc = load_rows(WECHAT_XLSX)
        assert enc == "xlsx"
        assert detect(rows).profile is WECHAT

    def test_card_payment_lands_on_card(self, parsed):
        mcd = next(t for t in parsed if t.merchant_raw == "麦当劳")
        assert (mcd.amount, mcd.direction) == (2350, "expense")
        assert mcd.account_hint == "招商银行信用卡(0575)"
        assert mcd.time == dt.time(11, 32)

    def test_income_without_method_goes_to_change(self, parsed):
        red = next(t for t in parsed if t.merchant_raw == "小明" and t.direction == "income")
        assert red.account_hint == "零钱"
        assert red.category_hint == "income.redpacket"

    def test_redpacket_sent(self, parsed):
        sent = next(t for t in parsed if t.merchant_raw == "小明" and t.direction == "expense")
        assert sent.amount == 6666
        assert sent.category_hint == "social.redpacket"

    def test_transfer_from_person(self, parsed):
        t = next(t for t in parsed if t.merchant_raw == "张三")
        assert (t.amount, t.category_hint) == (1000000, "income.transfer")

    def test_partial_refund_keeps_both_rows(self, parsed):
        rows = [t for t in parsed if t.merchant_raw == "中铁网络"]
        assert sorted((t.direction, t.amount) for t in rows) == [("expense", 7500), ("income", 3800)]
        refund = next(t for t in rows if t.direction == "income")
        assert refund.category_hint == "income.refund"
        original = next(t for t in rows if t.direction == "expense")
        assert "已退款" in (original.memo or "")

    def test_withdrawal_splits_fee(self, parsed):
        transfer = next(t for t in parsed if t.transfer and t.merchant_raw.startswith("零钱提现"))
        assert transfer.amount == 500000  # 5005 − 5 元服务费
        assert transfer.account_hint == "零钱"
        assert method_key(transfer.counterpart_hint) == "中国银行(6721)"
        fee = next(t for t in parsed if t.merchant_raw == "提现服务费")
        assert (fee.amount, fee.category_hint, fee.account_hint) == (500, "finance.fee", "零钱")

    def test_recharge_flows_into_change(self, parsed):
        t = next(t for t in parsed if t.transfer and t.merchant_raw.startswith("零钱充值"))
        assert (t.account_hint, t.direction, t.amount) == ("零钱", "income", 10000)
        assert method_key(t.counterpart_hint) == "中国银行(6721)"

    def test_goods_column_gives_fallback(self, parsed):
        t = next(t for t in parsed if t.merchant_raw == "啫啫煲（某店）")
        assert t.category_fallback == "food.dining"
        assert t.memo == "美团/大众点评点餐"  # 订单号去掉

    def test_failed_excluded(self, parsed):
        failed = next(t for t in parsed if t.merchant_raw == "某商店")
        assert failed.excluded and failed.exclude_reason == "failed"


class TestPaymentMethods:
    def test_key_unifies_card_spellings(self):
        assert method_key("中国银行储蓄卡(6721)") == method_key("中国银行(6721)") == "中国银行(6721)"
        assert method_key("招商银行信用卡（0575）") == "招商银行(0575)"

    def test_new_account_types(self):
        assert new_account_for("招商银行信用卡(0575)").type.value == "credit_card"
        assert new_account_for("中国银行储蓄卡(6721)").type.value == "bank"
        assert new_account_for("零钱").name == "微信零钱"


# --------------------------------------------------------------------------
# 端到端：预览 → 导入 → 确认
# --------------------------------------------------------------------------


@pytest.fixture()
def cn_client(client: TestClient):
    res = client.post(
        "/api/setup",
        json={"username": "cn", "password": "password123", "locale": "zh-CN", "region": "CN"},
    )
    assert res.status_code == 201, res.text
    return client


def _upload(content: bytes, name: str = "微信支付账单(20260901-20260930).xlsx"):
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return [("files", (name, content, mime))]


class TestWechatImport:
    def test_preview_lists_payment_methods(self, cn_client: TestClient):
        res = cn_client.post("/api/imports/csv/preview", files=_upload(WECHAT_XLSX))
        assert res.status_code == 200, res.text
        body = res.json()
        f = body["files"][0]
        assert f["profile"] == "wechat" and f["multi_account"] and not f["currency_mismatch"]
        methods = {m["key"]: m for m in body["payment_methods"]}
        assert list(methods)[0] == "零钱"
        assert methods["招商银行(0575)"]["new_type"] == "credit_card"
        assert methods["招商银行(0575)"]["new_name"] == "招商银行信用卡 0575"
        assert methods["中国银行(6721)"]["new_type"] == "bank"
        assert all(m["account_id"] is None for m in methods.values())

    def test_import_creates_accounts_and_routes_rows(self, cn_client: TestClient):
        res = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]})
        assert res.status_code == 201, res.text
        detail = res.json()
        assert any(w.startswith("accounts_created|") for w in detail["warnings"])

        accounts = {a["name"]: a for a in cn_client.get("/api/accounts").json()}
        assert {"微信零钱", "招商银行信用卡 0575", "中国银行储蓄卡 6721"} <= set(accounts)
        card = accounts["招商银行信用卡 0575"]
        assert card["type"] == "credit_card"

        rows = detail["rows"]
        mcd = next(r for r in rows if r["merchant_raw"] == "麦当劳")
        assert mcd["account_id"] == card["id"]
        assert mcd["amount"] == 2350
        assert mcd["category_id"] is not None  # 词典：麦当劳 → 堂食

        withdrawal = next(r for r in rows if r["merchant_raw"].startswith("零钱提现 "))
        assert withdrawal["transfer_hint"]
        assert withdrawal["counterpart_account_id"] == accounts["中国银行储蓄卡 6721"]["id"]

        # 确认后：零钱余额 = 收入 200 + 10000 + 38 + 充值 100 − 支出 22 − 66.66 − 75 − 提现 5000 − 服务费 5
        res = cn_client.post(f"/api/imports/{detail['batch']['id']}/confirm")
        assert res.status_code == 200, res.text
        assert res.json()["transfers"] == 2

        balances = {a["name"]: a["balance"] for a in cn_client.get("/api/accounts").json()}
        assert balances["招商银行信用卡 0575"] == -2350
        unknown_shop = next(r for r in rows if r["merchant_raw"] == "啫啫煲（某店）")
        assert unknown_shop["category_id"] is not None  # 商品列「点餐」兜底
        assert balances["中国银行储蓄卡 6721"] == 500000 - 10000

    def test_mapping_is_remembered(self, cn_client: TestClient):
        cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]})
        body = cn_client.post("/api/imports/csv/preview", files=_upload(WECHAT_XLSX)).json()
        assert all(m["account_id"] is not None for m in body["payment_methods"])

    def test_explicit_mapping_to_existing_account(self, cn_client: TestClient):
        acc = cn_client.post(
            "/api/accounts", json={"name": "招行信用卡", "type": "credit_card", "opening_balance": 0}
        ).json()
        res = cn_client.post(
            "/api/imports/csv",
            files=_upload(WECHAT_XLSX),
            data={"account_ids": ["0"], "payment_accounts": json.dumps({"招商银行信用卡(0575)": acc["id"]})},
        )
        assert res.status_code == 201, res.text
        mcd = next(r for r in res.json()["rows"] if r["merchant_raw"] == "麦当劳")
        assert mcd["account_id"] == acc["id"]
        names = [a["name"] for a in cn_client.get("/api/accounts").json()]
        assert "招商银行信用卡 0575" not in names

    def test_reimport_flags_duplicates(self, cn_client: TestClient):
        first = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]}).json()
        cn_client.post(f"/api/imports/{first['batch']['id']}/confirm")
        again = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]}).json()
        active = [r for r in again["rows"] if not r["excluded"]]
        assert active and all(r["dup_status"] == "duplicate" for r in active)

    def test_fee_row_is_expense_not_transfer(self, cn_client: TestClient):
        rows = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]}).json()["rows"]
        fee = next(r for r in rows if r["merchant_raw"] == "提现服务费")
        assert not fee["transfer_hint"]  # 词典里「零钱提现」是转账，但微信明说这是支出
        assert fee["category_id"] is not None

    def test_same_day_rides_at_different_times_are_two(self, cn_client: TestClient):
        """同一天两次 2 元地铁：微信给了时刻，不是重复；重导时各自对上各自。"""
        rides = [
            [serial(2026, 9, 12, 8, 1), "商户消费", "深圳地铁", "深圳地铁", "支出", "2", "零钱", "支付成功", "a1", "/", "/"],
            [serial(2026, 9, 12, 18, 30), "商户消费", "深圳地铁", "深圳地铁", "支出", "2", "零钱", "支付成功", "a2", "/", "/"],
        ]
        content = make_xlsx(PREAMBLE + [HEADER] + rides)
        first = cn_client.post("/api/imports/csv", files=_upload(content), data={"account_ids": ["0"]}).json()
        assert [r["dup_status"] for r in first["rows"]] == ["none", "none"]
        cn_client.post(f"/api/imports/{first['batch']['id']}/confirm")

        again = cn_client.post("/api/imports/csv", files=_upload(content), data={"account_ids": ["0"]}).json()
        assert [r["dup_status"] for r in again["rows"]] == ["duplicate", "duplicate"]
        assert again["rows"][0]["dup_ref_id"] != again["rows"][1]["dup_ref_id"]

    def test_dup_reason_uses_ledger_decimals(self, cn_client: TestClient):
        first = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]}).json()
        cn_client.post(f"/api/imports/{first['batch']['id']}/confirm")
        again = cn_client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]}).json()
        mcd = next(r for r in again["rows"] if r["merchant_raw"] == "麦当劳")
        assert mcd["dup_reason"].endswith("¥23.50")

    def test_jp_ledger_rejects_cny_file(self, client: TestClient):
        client.post("/api/setup", json={"username": "jp", "password": "password123"})
        preview = client.post("/api/imports/csv/preview", files=_upload(WECHAT_XLSX)).json()
        assert preview["files"][0]["currency_mismatch"]
        res = client.post("/api/imports/csv", files=_upload(WECHAT_XLSX), data={"account_ids": ["0"]})
        assert res.status_code == 400
        assert res.json()["detail"] == "csv_currency_mismatch"

    def test_mapped_csv_uses_ledger_decimals(self, cn_client: TestClient):
        acc = cn_client.post("/api/accounts", json={"name": "现金", "type": "cash", "opening_balance": 0}).json()
        csv_bytes = "日期,摘要,金额\n2026-09-01,便利店,12.50\n".encode("utf-8")
        res = cn_client.post(
            "/api/imports/csv",
            files=[("files", ("bank.csv", csv_bytes, "text/csv"))],
            data={"account_ids": [str(acc["id"])]},
        )
        assert res.status_code == 201, res.text
        assert res.json()["rows"][0]["amount"] == 1250
