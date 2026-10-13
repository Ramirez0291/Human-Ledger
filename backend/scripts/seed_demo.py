"""灌入演示数据。

数据全部取自 docs/测试图片/ 里的真实截图（需求书附录 A），因此这个脚本
同时是一次端到端验证：账户、收支、转账、分期、对账、分类学习都会被走到。

用法（需先启动后端）：
    backend/.venv/Scripts/python.exe scripts/seed_demo.py [用户名] [密码]

注意：会往当前数据库里写入数据。清空可直接删除 data/ledger.db 后重新迁移。
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8000/api"


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "reigetsu"
    password = sys.argv[2] if len(sys.argv) > 2 else "kakeibo2026"

    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        # 数据库为空时直接完成初始化，省去先开浏览器的步骤
        if c.get("/status").json()["needs_setup"]:
            r = c.post(
                "/setup",
                json={"username": username, "password": password, "locale": "zh-CN"},
            )
            r.raise_for_status()
            print(f"已初始化用户：{username}")
        else:
            res = c.post("/login", json={"username": username, "password": password})
            if res.status_code != 200:
                print(f"登录失败（{res.status_code}）：{res.text}")
                print("请传入正确的用户名密码：seed_demo.py <用户名> <密码>")
                sys.exit(1)

        # ---- 类目索引 ----
        cats: dict[str, int] = {}

        def walk(nodes):
            for n in nodes:
                cats[n["key"]] = n["id"]
                walk(n["children"])

        walk(c.get("/categories").json())

        # ---- 账户 ----
        # institution 填上机构名，M2 导入截图时可据此自动对应账户
        account_specs = [
            # 期初余额必须是**最早一笔录入交易之前**的余额，而不是截图上任意一行的残高。
            # 截图 26.08.27 那行的残高 20,692 是「ラクテンカードサービス −25,980」**之后**的值；
            # 若拿它当期初，又把那笔还款录一遍，这 25,980 就被扣了两次。
            # 逐行倒推：20,692 + 25,980 = 46,672 才是这批交易之前的余额。
            ("三井住友銀行", "bank", "三井住友銀行", 46672, "#1f6f4f"),
            ("Olive クレジット", "credit_card", "三井住友カード", 0, "#3D8FE8"),
            # 信用卡的期初余额是「记账开始时尚未还清的金额」，记为负数。
            # 8/27 那笔 25,980 円还的是更早账期的消费（不在截图范围内），
            # 不设期初就会让还款凭空把余额推成正数。设了之后余额为 −16,907，
            # 与截图上「2026/09 ¥16,907」的应付金额一致。
            ("楽天カード", "credit_card", "楽天カード", -25980, "#E8663D"),
            ("ビックカメラJ-WEST", "credit_card", "ジェイアール西日本カード", 0, "#8B5CF6"),
            ("PayPay", "emoney", "PayPay", 5000, "#06B6D4"),
            ("モバイルICOCA", "prepaid", "JR西日本", 0, "#10B981"),
            ("現金", "cash", None, 15000, "#64748B"),
        ]
        accounts: dict[str, int] = {}
        existing = {a["name"]: a["id"] for a in c.get("/accounts").json()}
        for name, type_, institution, opening, color in account_specs:
            if name in existing:
                accounts[name] = existing[name]
                continue
            r = c.post(
                "/accounts",
                json={
                    "name": name,
                    "type": type_,
                    "institution": institution,
                    "opening_balance": opening,
                    "color": color,
                },
            )
            r.raise_for_status()
            accounts[name] = r.json()["id"]
        print(f"账户：{len(accounts)} 个")

        # ---- 交易 ----
        # (账户, 日期, 方向, 金额, 商家原文, 类目 key)
        rows = [
            # === 三井住友銀行 口座明細 ===
            ("三井住友銀行", "2026-09-07", "income", 2402, "振込 ｱﾏｿﾞﾝｼﾞﾔﾊﾟﾝ(ﾄﾞ", "income.refund"),
            ("三井住友銀行", "2026-09-02", "income", 1, "振込 ｱﾏｿﾞﾝｼﾞﾔﾊﾟﾝ(ﾄﾞ", "income.refund"),
            # 国民年金：在日外国人的高频大额支出，正是单列「税金・社会保険」的理由
            ("三井住友銀行", "2026-09-01", "expense", 41208, "PE ｼﾔｶｲﾎｹﾝﾘﾖｳﾄｳ(ｺﾂｷﾝ)", "tax.pension"),
            ("三井住友銀行", "2026-09-01", "income", 68186, "振込 ﾑ-ﾑ-ｼﾖｳｹﾝ(ｶ", "income.other"),

            # === Olive クレジット（2026年9月分 明細）===
            ("Olive クレジット", "2026-08-31", "expense", 3652, "ＡＮＴＨＲＯＰＩＣ＊　ＣＬＡＵＤＥ　ＳＵ", "comm.subscription"),
            ("Olive クレジット", "2026-08-31", "expense", 1841, "ライフ此花伝法店", "food.groceries"),
            ("Olive クレジット", "2026-08-30", "expense", 1080, "ＳＰＯＴＩＦＹ　Ｐ４６４２０７４Ａ７", "entertainment.streaming"),
            ("Olive クレジット", "2026-08-29", "expense", 3064, "ＡＭＡＺＯＮ．ＣＯ．ＪＰ", "daily.supplies"),
            ("Olive クレジット", "2026-08-29", "expense", 1520, "サブウェイ　なんばシティ店／ＮＦＣ", "food.dining"),
            ("Olive クレジット", "2026-08-28", "expense", 622, "ミニストップ　日本橋３丁目交差点東店", "food.convenience"),

            # === Olive クレジット（2026年10月分 明細）===
            ("Olive クレジット", "2026-09-02", "expense", 842, "ライフ此花伝法店", "food.groceries"),
            # 下面两笔同额同商家、日期相差一天，是真实的两笔消费。
            # 它们会触发 L3b「可能重复」黄标，但绝不能被自动合并（附录 A.4.2）。
            ("Olive クレジット", "2026-09-02", "expense", 230, "ミニストップ　日本橋３丁目交差点東店", "food.convenience"),
            ("Olive クレジット", "2026-09-01", "expense", 230, "ミニストップ　日本橋３丁目交差点東店", "food.convenience"),
            ("Olive クレジット", "2026-08-26", "expense", 200, "関西電力電気２０２６／０９", "utilities.electricity"),

            # === 楽天カード ===
            # 前三笔在截图上只有第一行显示日期，其余靠「日期向上继承」得出（附录 A.3.1）
            ("楽天カード", "2026-08-20", "expense", 770, "JCB ミニストツプ", "food.convenience"),
            ("楽天カード", "2026-08-20", "expense", 697, "JCB ミニストツプ", "food.convenience"),
            ("楽天カード", "2026-08-20", "expense", 165, "JCB ミニストツプ", "food.convenience"),
            ("楽天カード", "2026-08-20", "expense", 1200, "JCB トヨタハクブツカン エスビー", "entertainment.hobby"),
            ("楽天カード", "2026-08-15", "expense", 1380, "JCB ヨロジヨウロウエスエ-クダリ", "transport.highway"),
            ("楽天カード", "2026-08-15", "expense", 1156, "ENEOS（J）　99993 6342", "transport.fuel"),
            ("楽天カード", "2026-08-14", "expense", 4994, "JCB ヒラメテイ", "food.dining"),
            ("楽天カード", "2026-08-14", "expense", 867, "イデミツ（アポロステーション）", "transport.fuel"),
            ("楽天カード", "2026-08-14", "expense", 894, "伊藤忠エネクス", "transport.fuel"),
            # ⚠ 下面两笔是高速公路 ETC 的往返两程：同日、同额、词元相同但顺序相反。
            #   它们是真实的两笔，规范化绝不能对词元排序（附录 A.4.1）。
            ("楽天カード", "2026-08-02", "expense", 620, "ETCカード売上 ホウライ　　　ニシイシキリホンセ", "transport.highway"),
            ("楽天カード", "2026-08-02", "expense", 620, "ETCカード売上 ニシイシキリホンセン ホウライ", "transport.highway"),
            ("楽天カード", "2026-08-02", "expense", 790, "ETCカード売上 ヒガシオオサカイリ テンポウザンシ", "transport.highway"),
            ("楽天カード", "2026-08-02", "expense", 840, "ETCカード売上 ワンガンマイシマ　ヒガシオオサ", "transport.highway"),
            ("楽天カード", "2026-07-26", "expense", 770, "ETCカード売上 シマヤ　　　モリシヨウジデ", "transport.highway"),
            ("楽天カード", "2026-07-12", "expense", 280, "ETCカード売上 シヨウレンジガワ ヒメジマデ", "transport.highway"),

            # === ビックカメラJ-WEST（8月支払分）===
            # 截图上日期无年份，仅有「8月」支払月标签，年份靠推断得出（附录 A.3.2）
            ("ビックカメラJ-WEST", "2026-06-13", "expense", 1006, "伊藤忠エネクス", "transport.fuel"),
            ("ビックカメラJ-WEST", "2026-06-23", "expense", 2331, "ららぽーと門真／ＭＯＰ大阪門真", "daily.supplies"),
            ("ビックカメラJ-WEST", "2026-06-23", "expense", 7949, "ららぽーと門真／ＭＯＰ大阪門真", "beauty.clothing"),
            ("ビックカメラJ-WEST", "2026-06-26", "expense", 600, "アマゾンプライムカイヒ", "comm.subscription"),
            ("ビックカメラJ-WEST", "2026-06-28", "expense", 479, "ＡＰ／ＱＰ／ダイエー　エスエム", "food.groceries"),
            ("ビックカメラJ-WEST", "2026-06-29", "expense", 71113, "アートヒツコシセンターカブシキガイシ", "housing"),
            ("ビックカメラJ-WEST", "2026-06-30", "expense", 3331, "ゼンニツシヨクチエーントリシマテン", "food.groceries"),
            ("ビックカメラJ-WEST", "2026-07-01", "expense", 510, "ナカウ", "food.dining"),
            # === ビックカメラJ-WEST（9月支払分）===
            ("ビックカメラJ-WEST", "2026-07-26", "expense", 600, "アマゾンプライムカイヒ", "comm.subscription"),
            ("ビックカメラJ-WEST", "2026-08-09", "expense", 8886, "ソフトバンク（Ｂ）", "comm.mobile"),

            # === PayPay 取引履歴 ===
            # ⚠ 截图中还有一笔 2026/05/26 Steam 1,000 円，状态为「支払い失敗」、
            #   金额带删除线。那笔钱根本没花出去，必须排除（附录 A.2.1）。
            #   此处刻意不录入，正是识别层将来要实现的行为。
            ("PayPay", "2026-05-13", "expense", 620, "Steam", "entertainment.hobby"),
            ("PayPay", "2026-05-13", "expense", 1595, "大阪市水道局（水道料金、下水道使用料、修繕料、給水装置工事費）", "utilities.water"),
            ("PayPay", "2026-05-13", "expense", 1540, "Steam", "entertainment.hobby"),
            ("PayPay", "2026-05-11", "expense", 921, "Steam", "entertainment.hobby"),
        ]

        for name, date, direction, amount, merchant, cat_key in rows:
            r = c.post(
                "/transactions",
                json={
                    "account_id": accounts[name],
                    "date": date,
                    "direction": direction,
                    "amount": amount,
                    "merchant_raw": merchant,
                    "category_id": cats.get(cat_key),
                },
            )
            r.raise_for_status()
        print(f"交易：{len(rows)} 笔")

        # ---- 分期付款 ----
        # 楽天モバイル製品代：総額 41,487 円 / 48回払い の 17回目。
        # 口径已确认：amount 记**当期金额**，総額仅作参考，不计入当月支出。
        r = c.post(
            "/transactions",
            json={
                "account_id": accounts["楽天カード"],
                "date": "2026-09-01",
                "direction": "expense",
                "amount": 864,  # 41,487 ÷ 48
                "merchant_raw": "楽天モバイル製品代　704861",
                "category_id": cats.get("comm.mobile"),
                "memo": "2025/03/27 購入・48回払い",
                "installment_current": 17,
                "installment_total": 48,
                "installment_total_amount": 41487,
            },
        )
        r.raise_for_status()
        print("分期：1 笔（当期金额入账，总额仅作参考）")

        # ---- 转账 ----
        # 这三笔若记成支出，都会导致同一笔钱被统计两次
        transfers = [
            # 信用卡还款：三井住友銀行 → 楽天カード（样本中的「ﾗｸﾃﾝｶｰﾄﾞｻｰﾋﾞｽ 25,980円 −」）
            ("三井住友銀行", "楽天カード", "2026-08-27", 25980, "カード引落"),
            # 交通 IC 充值：J-WEST カード → モバイルICOCA
            ("ビックカメラJ-WEST", "モバイルICOCA", "2026-06-16", 2000, "モバイルICOCA チャージ"),
            # ATM 取现：银行 → 现金。
            # 刻意放在对账日 2026-09-07 之后——截图上没有这笔，放在对账日之前
            # 会让对账结果凭空出现差额。
            ("三井住友銀行", "現金", "2026-09-08", 30000, "ATM 出金"),
        ]
        for src, dst, date, amount, memo in transfers:
            r = c.post(
                "/transactions/transfer",
                json={
                    "from_account_id": accounts[src],
                    "to_account_id": accounts[dst],
                    "date": date,
                    "amount": amount,
                    "memo": memo,
                },
            )
            r.raise_for_status()
        print(f"转账：{len(transfers)} 笔")

        # ---- 对账 ----
        # 三井住友銀行截图上 2026/09/07 时点的实际余额为 50,073 円。
        # 若账目完整，系统算出的余额应与之一致。
        r = c.post(
            f"/accounts/{accounts['三井住友銀行']}/reconcile",
            json={"date": "2026-09-07", "actual_balance": 50073, "note": "截图残高"},
        )
        r.raise_for_status()
        rec = r.json()
        print(
            f"对账：三井住友銀行 计算 {rec['computed_balance']:,} / 实际 {rec['actual_balance']:,}"
            f" → 差额 {rec['diff']:,}"
        )
        if rec["diff"] == 0:
            print("      余额一致，账目完整。")
        else:
            print("      存在差额，说明有交易未录入（这正是对账功能要暴露的问题）。")

        # ---- 结果 ----
        for ym in ("2026-08", "2026-09"):
            s = c.get(f"/summary?year_month={ym}").json()
            print(
                f"{ym}：支出 {s['expense']:,} / 收入 {s['income']:,} / 结余 {s['net']:,}"
                f"（{s['transaction_count']} 笔）"
            )


if __name__ == "__main__":
    main()
