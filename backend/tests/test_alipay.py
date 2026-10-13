"""支付宝交易明细导入的测试。

夹具按支付宝「用于个人对账」流水的**格式**构造（GBK、说明区 + 列标题、订单号后带 Tab、行末多一个逗号），
内容为虚构数据。真实流水含姓名与手机号，不进仓库。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.services.importing.csv_source import ALIPAY, decode, detect, parse_csv, read_rows

PREAMBLE = """------------------------------------------------------------------------------------
导出信息：
姓名：测试
支付宝账户：138****0000
起始时间：[2026-09-01 00:00:00]    终止时间：[2026-09-30 23:59:59]
导出交易类型：[全部]
共12笔记录
收入：1笔 88.00元
支出：7笔 1000.00元
不计收支：4笔 500.00元

特别提示：
1.本明细仅供个人对账使用。

------------------------支付宝支付科技有限公司  电子客户回单------------------------
交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注,
"""

ROWS = [
    # 绑卡 + 优惠：金额是实付，「优惠」不是账户
    "2026-09-01 18:37:43,爱车养车,某车品旗舰店,abc***@163.com,摩托车头盔蓝牙耳机,支出,678.94,中国银行储蓄卡(6721)&优惠,交易成功,2026090123001\t,T200P001\t,,",
    # 余额支付；交易分类只给大类，词典认得出「瑞幸」→ 用更细的子类
    "2026-09-02 08:10:00,餐饮美食,瑞幸咖啡,lk***@luckin.com,生椰拿铁,支出,9.90,余额,交易成功,2026090223002\t,T200P002\t,,",
    # 淘宝店名没意义，靠支付宝的交易分类
    "2026-09-03 21:00:00,数码电器,tb5408639508,151******29,移动硬盘1T,支出,599.00,招商银行信用卡(0575),支付成功,2026090323003\t,T200P003\t,,",
    # 先用后付的 0 元占位行
    "2026-09-04 10:00:00,日用百货,tb127782865,180******17,洗衣粉,支出,0.00,,支付成功,2026090423004\t,T200P004\t,,",
    # 订单关闭（没付款）
    "2026-09-05 10:00:00,服饰装扮,某服饰店,che***@163.com,衬衫,不计收支,456.17,,交易关闭,2026090523005\t,T200P005\t,,",
    # 关闭订单的退款：钱出去又回来，连同原订单一起不算
    "2026-09-05 12:00:00,退款,某服饰店,che***@163.com,退款-衬衫,不计收支,456.17,中国银行储蓄卡(6721),退款成功,2026090523005_1\t,T200P005\t,,",
    # 已完成订单的部分退款：收入，归入退款
    "2026-09-06 12:00:00,退款,某车品旗舰店,abc***@163.com,退款-摩托车头盔蓝牙耳机,不计收支,50.00,中国银行储蓄卡(6721),退款成功,2026090123001_2\t,T200P001\t,,",
    # 余额宝转入：转账
    "2026-09-07 09:00:00,投资理财,余额宝,/,余额宝-转入,不计收支,500.00,中国银行储蓄卡(6721),交易成功,2026090723007\t,\t,,",
    # 收到的转账
    "2026-09-08 20:00:00,转账红包,张三,zs***@qq.com,转账,收入,88.00,余额,交易成功,2026090823008\t,\t,,",
    # 花呗付款
    "2026-09-09 13:00:00,交通出行,滴滴出行,didi***@xiaojukeji.com,滴滴快车,支出,23.16,花呗,交易成功,2026090923009\t,T200P009\t,,",
]

ALIPAY_CSV = (PREAMBLE + "\n".join(ROWS) + "\n").encode("gbk")


@pytest.fixture()
def parsed():
    result, det, enc = parse_csv(ALIPAY_CSV, "支付宝交易明细(20260901-20260930).csv")
    assert det.profile is ALIPAY
    assert enc == "gb18030"
    return result.transactions


def by(parsed, merchant, direction=None):
    return [t for t in parsed if t.merchant_raw == merchant and (direction is None or t.direction == direction)]


class TestDecode:
    def test_gbk_not_read_as_shift_jis(self):
        text, enc = decode(ALIPAY_CSV)
        assert enc == "gb18030"
        assert "支付宝" in text

    def test_detect(self):
        text, _ = decode(ALIPAY_CSV)
        assert detect(read_rows(text)).profile is ALIPAY


class TestAlipayParse:
    def test_card_with_discount(self, parsed):
        t = by(parsed, "某车品旗舰店", "expense")[0]
        assert (t.amount, t.account_hint, t.category_hint) == (67894, "中国银行储蓄卡(6721)", "transport.car")
        assert t.time == dt.time(18, 37, 43)
        assert t.memo == "摩托车头盔蓝牙耳机"

    def test_balance_is_alipay_wallet(self, parsed):
        t = by(parsed, "瑞幸咖啡")[0]
        assert t.account_hint == "支付宝余额"
        assert t.category_hint == "food"

    def test_zero_and_closed_excluded(self, parsed):
        assert by(parsed, "tb127782865")[0].exclude_reason == "zero_amount"
        closed = [t for t in by(parsed, "某服饰店") if t.direction == "expense"][0]
        assert closed.exclude_reason == "closed"

    def test_refund_of_closed_order_excluded(self, parsed):
        refund = [t for t in by(parsed, "某服饰店") if t.direction == "income"][0]
        assert refund.excluded and refund.exclude_reason == "refund_of_closed"

    def test_partial_refund_is_income(self, parsed):
        refund = by(parsed, "某车品旗舰店", "income")[0]
        assert not refund.excluded
        assert (refund.amount, refund.category_hint, refund.account_hint) == (5000, "income.refund", "中国银行储蓄卡(6721)")

    def test_yuebao_is_transfer(self, parsed):
        t = next(t for t in parsed if t.transfer)
        assert (t.amount, t.account_hint, t.counterpart_hint) == (50000, "中国银行储蓄卡(6721)", "余额宝")

    def test_transfer_received(self, parsed):
        t = by(parsed, "张三")[0]
        assert (t.direction, t.category_hint, t.account_hint) == ("income", "income.transfer", "支付宝余额")

    def test_huabei(self, parsed):
        t = by(parsed, "滴滴出行")[0]
        assert t.account_hint == "花呗"

    def test_expense_total_matches_statement(self, parsed):
        """支出合计按支付宝的口径（不含 0 元占位、关闭订单）。"""
        spent = sum(t.amount for t in parsed if not t.excluded and not t.transfer and t.direction == "expense")
        assert spent == 67894 + 990 + 59900 + 2316


@pytest.fixture()
def cn_client(client: TestClient):
    res = client.post(
        "/api/setup",
        json={"username": "cn", "password": "password123", "locale": "zh-CN", "region": "CN"},
    )
    assert res.status_code == 201, res.text
    return client


def _upload(content: bytes, name: str = "支付宝交易明细(20260901-20260930).csv"):
    return [("files", (name, content, "text/csv"))]


class TestAlipayImport:
    def test_preview_methods(self, cn_client: TestClient):
        body = cn_client.post("/api/imports/csv/preview", files=_upload(ALIPAY_CSV)).json()
        f = body["files"][0]
        assert f["profile"] == "alipay" and f["multi_account"] and f["encoding"] == "gb18030"
        keys = [m["key"] for m in body["payment_methods"]]
        assert keys[0] == "支付宝余额"
        assert {"中国银行(6721)", "招商银行(0575)", "花呗", "余额宝"} <= set(keys)
        new = {m["key"]: (m["new_name"], m["new_type"]) for m in body["payment_methods"]}
        assert new["支付宝余额"] == ("支付宝余额", "emoney")
        assert new["花呗"] == ("花呗", "credit_card")
        assert new["余额宝"] == ("余额宝", "investment")

    def test_import_categories_and_accounts(self, cn_client: TestClient):
        res = cn_client.post("/api/imports/csv", files=_upload(ALIPAY_CSV), data={"account_ids": ["0"]})
        assert res.status_code == 201, res.text
        rows = res.json()["rows"]
        cats = {}
        for c in cn_client.get("/api/categories").json():
            cats[c["id"]] = c["key"]
            cats.update({ch["id"]: ch["key"] for ch in c.get("children", [])})

        luckin = next(r for r in rows if r["merchant_raw"] == "瑞幸咖啡")
        assert cats[luckin["category_id"]] == "food.cafe"  # 词典的子类细化支付宝的大类
        disk = next(r for r in rows if r["merchant_raw"] == "tb5408639508")
        assert cats[disk["category_id"]] == "shopping.digital"
        yuebao = next(r for r in rows if r["merchant_raw"].startswith("投资理财"))
        assert yuebao["transfer_hint"] and yuebao["counterpart_account_id"] is not None

        names = {a["name"] for a in cn_client.get("/api/accounts").json()}
        assert "微信零钱" not in names  # 支付宝账单里没有零钱，不该凭空建

    def test_shares_card_accounts_with_wechat(self, cn_client: TestClient):
        """同一张卡在微信与支付宝账单里落到同一个账户。"""
        from tests.test_region_cn import WECHAT_XLSX

        cn_client.post(
            "/api/imports/csv",
            files=[("files", ("微信.xlsx", WECHAT_XLSX, "application/octet-stream"))],
            data={"account_ids": ["0"]},
        )
        card_id = next(a["id"] for a in cn_client.get("/api/accounts").json() if a["name"] == "中国银行储蓄卡 6721")
        body = cn_client.post("/api/imports/csv/preview", files=_upload(ALIPAY_CSV)).json()
        boc = next(m for m in body["payment_methods"] if m["key"] == "中国银行(6721)")
        assert boc["account_id"] == card_id

        rows = cn_client.post("/api/imports/csv", files=_upload(ALIPAY_CSV), data={"account_ids": ["0"]}).json()["rows"]
        helmet = next(r for r in rows if r["merchant_raw"] == "某车品旗舰店" and r["direction"] == "expense")
        assert helmet["account_id"] == card_id
        assert sum(1 for a in cn_client.get("/api/accounts").json() if "6721" in a["name"]) == 1
