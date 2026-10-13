# 人类账本

个人记账 Web 应用，支持手动录入与账单 / 截图导入，自动去重与分类。核心与地区无关，随地区变化的部分做成**地区包**：

- **日本**（日元）：三井住友 / 楽天カード / PayPay 等 CSV，日式家計簿类目
- **中国**（人民币，记到分）：微信支付账单（xlsx / CSV）与支付宝交易明细（GBK CSV）按支付方式分账户入账，同一张卡在两份账单里是同一个账户；红包、外卖、打车等中国类目

每个用户注册时选定地区（之后不可改），同一个部署可以同时有日本账本和中国账本。


> **不懂编程也能装**：把这个文件夹交给 AI 编程助手（Claude Code、Codex、Cursor 等），对它说「帮我把人类账本装好，并教我怎么用」。它会按 [AGENTS.md](AGENTS.md) 一步步来。装好以后双击 `start-windows.bat`（macOS 是 `start-mac.command`）启动。

**当前进度：M3 报表已完成，地区包（日本 / 中国）已接入。** 支持粘贴截图文字或上传银行 / 信用卡 CSV（三井住友銀行 / 三井住友カード / 楽天カード / PayPay / 微信支付账单 / 支付宝交易明细 自动识别），自动去重、分类，进待确认区核对后入账；报表页有趋势、分类占比（可下钻）、商家排行与账户视图；可导出 CSV 与完整备份。图片 OCR 待接入。

---

## 快速开始

### 方式一：Docker（推荐用于服务器部署）

```bash
cp .env.example .env
```

编辑 `.env`，设置 `SECRET_KEY`（生产环境必填，留空会拒绝启动）：

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

主要给中国用户用的部署，顺便把 `DEFAULT_REGION=CN`、`TIMEZONE=Asia/Shanghai` 也改上（注册页仍可选地区）。

然后启动：

```bash
docker compose up -d
```

访问 http://localhost:8000 ，首次会引导设置用户名与密码。之后其他人可以自助注册各自独立的账本；个人部署可在 `.env` 里设 `ALLOW_REGISTRATION=false` 关掉注册入口。

### 方式二：本地开发

需要 Python 3.11+ 与 Node 20+。

**后端**

```bash
cd backend
python -m venv .venv
```

Windows 用 `.venv\Scripts\activate`，macOS / Linux 用 `source .venv/bin/activate`，然后：

```bash
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

**前端**（另开一个终端）

```bash
cd frontend
npm install
npm run dev
```

开发时访问 http://localhost:5173 （Vite 会把 `/api` 代理到后端 8000 端口）。

前端执行 `npm run build` 后，后端会直接托管构建产物，此时单独访问 http://localhost:8000 即可。自用时也可以双击根目录的 `start-windows.bat` / `start-mac.command`：先迁移数据库，再启动服务，服务就绪后打开浏览器。

---

## 项目结构

```
├── backend/                 FastAPI + SQLAlchemy + Alembic
│   ├── alembic/             数据库迁移
│   ├── app/
│   │   ├── api/routers/     接口路由
│   │   ├── core/            配置、安全、依赖
│   │   ├── db/              模型与会话
│   │   ├── regions/         地区包：币种与小数位、时区、按金额量级定的常量；cn.py 是中国的类目树与商家词典
│   │   └── services/
│   │       ├── ocr/         截图识别 Provider（M2 接入，当前仅接口）
│   │       └── seed.py      预置类目种子数据
│   └── scripts/             开发辅助脚本
├── frontend/                React + TypeScript + Vite
│   └── src/i18n/locales/    语言词条，新增语言只需添加一个 JSON
├── AGENTS.md                给 AI 助手的安装、运行与使用说明（CLAUDE.md 引用它）
├── start-windows.bat        双击启动（macOS / Linux 用 start-mac.command）
├── docs/
│   ├── requirements.md      需求书
│   └── 测试图片/            真实截图样本，识别功能的基准用例
├── data/                    SQLite 数据库与上传的截图（不入版本库）
└── docker-compose.yml
```

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `python -m alembic revision --autogenerate -m "说明"` | 改完模型后生成迁移（在 `backend/` 下执行） |
| `python -m alembic upgrade head` | 应用迁移 |
| `python -m pytest` | 运行后端测试 |
| `python scripts/inspect_db.py` | 查看表结构与行数概览 |
| `python scripts/seed_demo.py` | 灌入演示数据（取自 `docs/测试图片/` 的真实账目） |
| `python scripts/renormalize.py` | **改动 `normalize.py` 后必须运行**：重算全库商家规范化与指纹 |
| `python scripts/reset_password.py [用户名]` | 忘记密码时重设为随机新密码并打印；不带参数列出所有用户名 |
| `python scripts/restore_backup.py <zip>` | 从「设置 → 备份」下载的 zip 恢复（**先停服务**；旧数据留作 `*.bak-时间戳`） |
| `npm run check:locales` | 检查三种语言词条是否一致（已接入 `npm run build`） |
| `npm run typecheck` | 前端类型检查 |

---

## 开发约定

- **金额一律为最小货币单位的整数**（日元存円、人民币存分，`app/regions` 的 `minor_unit`），数据库、API、前端均不出现浮点数。只在显示的最后一步除以 10^minor_unit（`lib/format.ts`），输入经 `parseAmount` 换回整数
- **地区包决定币种、时区、预置类目与商家词典**（`app/regions`）：日本的类目树与词典留在 `services/seed.py`、`categorize/dictionary.py`，其他地区放在 `app/regions/<地区>.py`，按 `user.region` 取。新增地区 = `REGIONS` 加一项 + 一棵类目树 + 一份词典（+ 前端 `lib/region.ts` 的单笔上限档位与节假日预设）。地区建用户时选定后不可改——同一个整数在两种币种下是两种金额
- **文件币种与账本币种不符的整份拒收**（`Profile.currency`）：微信账单导进日元账本会把 23.50 元当成 2,350 円
- **CSV 编码按「读得出几个明细用词」挑**（`csv_source.decode`）：UTF-8 之外，Shift_JIS（日本银行）与 GB18030（支付宝、国内银行）对同一份字节往往都解得开，只有解对的那种读得出「利用日」「交易时间」这类词。平手取 Shift_JIS
- **一份账单跨多个账户（微信、支付宝）时逐行落账户**：`RawTransaction.account_hint` 是「支付方式」原文，`payment_methods.method_key` 归一成「银行名(尾号)」再按映射换成账户；用户确认过的映射存在偏好 `payment_accounts`。绑卡支付记在那张卡上，不记在零钱上
- **来源给的类目提示只给大类时，词典的同类子类优先**（`Categorizer.refines`）：支付宝「餐饮美食」→ 餐饮，但「瑞幸」在词典里是奶茶咖啡，就用更细的
- **来源知道是不是转账时以来源为准**（`RawTransaction.transfer`）：微信的「中性交易」一定是转账；「支出 / 收入」一定不是，词典的转账提示不作数（否则「提现服务费」会因含「提现」被当成转账）
- **带时刻的两边时刻不同就不是重复**（`dedup.same_moment`）：微信、PayPay 精确到秒，同一天两次 2 元地铁是两笔；有一边没时刻（手记、截图）仍按指纹判
- **地区专属文案用 i18next 的 context**：`t(key, { context: regionContext() })` 先找 `key_CN` 再退回 `key`。日本版是基础文案
- **后端不返回已翻译文案**，只返回 i18n key，由前端渲染；类目名等业务数据通过 `category_names` 表按语言存储
- **配置文件（`alembic.ini`）必须保持 ASCII**——它由 configparser 以系统 locale 编码读取，在日文 Windows 上是 cp932，写入中文会导致启动失败
- **新增一种界面语言**：在 `frontend/src/i18n/locales/` 放一个 `<locale>.json`（含 `_meta.locale` 与 `_meta.nativeName`），前端自动发现；后端需在 `backend/app/services/seed.py` 的 `SUPPORTED_LOCALES` 与类目名称中补上对应语言
- **商家名规范化禁止对词元排序**，详见需求书附录 A.4.1（会把 ETC 往返两程误判为重复）。规范化管道在 `backend/app/services/normalize.py`，改动前先读 `tests/test_normalize.py`
- **转账必须成对生成、成对删除**：只删一条腿会让两个账户的余额同时出错且无任何报错。相关约束由 `tests/test_ledger.py` 守住
- **信用卡余额为负数**表示未偿还金额；期初余额要填「开始记账时尚未还清的金额」（负数），否则还款会把余额推成正数
- **分类词典的模式必须与商家名走同一条规范化管道**（`dictionary._norm` 调用 `normalize_merchant`），否则规范化规则一变词典就集体失效
- **判重查询不能假设指纹唯一**：CSV 批内不合并，同日同额同店的两笔会各自入账，同指纹的交易可以有多条。取一条作引用即可（`dedup.py` 用 `.limit(1)`）
- **待确认区的下拉框是懒渲染的**（`LazySelect`）：几百行 × 三个 select × 几十个 option 会撑出几万个 DOM 节点。新加的行内控件沿用这个做法，行组件保持 `memo`、回调保持稳定引用
- **改类别默认推给同批次同商家**（`apply_to_similar`），只推给用户没亲手改过的行。这是「简单快速地分类」的核心机制，改判别链时别绕开它
- **所有业务查询按 `user_id` 过滤**：已经是多用户系统，新增接口时从 `get_current_user` 拿 user 并加过滤，漏一处就是数据泄漏
- **CSV 批内不合并、截图批内合并**：银行不会重复导出，文件内相同行是真实的多笔；截图的滚动重叠才是重复
- **真实账单文件不进仓库**：含姓名与卡号。测试用 `tests/test_csv_source.py` 里按格式构造的虚构数据
- **报表与列表、导出共用一套筛选口径**：转账两条腿不计收支；按大分類筛选时包含其子类（`services/reports.category_scope`）。三处若各写一套，报表下钻后跳到流水页会对不上数
- **「除外」只作用于分析口径**：`exclude_from_analysis`、单笔上限、类目除外都只进 `services/reports.py` 的 `_apply_exclusions`，余额、流水、导出一律不受影响。新增报表板块要同时返回被除外的部分，别让金额悄悄消失
- **导入的重复在三处拦**：暂存时（L1–L3c，按账户比对）、确认时（`confirm._is_late_duplicate`：暂存时没查出、确认时账本里有了——两个草稿同时开着的情况）、事后（`services/importing/history.py` 的重叠检测，后导入的那份算多出来的）。CSV 格式认得出账户类型时，放错账户会被改放到对应账户，否则判重整个失效
- **卡商 CSV 的列按表头找，不写死列号**：同一家卡商不同年份的导出列数会变（楽天 2026/06 前后差一列）。夹具要覆盖新旧两种格式
- **信用卡还款、取现、充值、转入证券都是转账**：记成支出会与卡上的逐笔消费双计。词典里 `transfer=True` 的条目同时驱动导入时的对方账户预填和报表「大额支出」里的就地改记（`POST /transactions/{id}/to-transfer`）
- **余额有两种算法**（`services/balances.py` 顶部）：用户偏好 `ledger_mode`（relaxed = 轻松 / strict = 界面上叫「合规模式」），默认 relaxed（以最近快照为起点、信用卡封顶 0、现金 / 钱包保底 0）。任何展示余额的地方都走 `compute_balances(db, user_id)`，别自己 SUM；对账的 `computed_balance` 仍按严格口径记录
- **合规模式的氛围只由 `.app-shell[data-tension]` 驱动**（`compliance.css`），等级来自 `services/compliance.py`。新加的动效必须在 `prefers-reduced-motion` 块里一并关掉
- **CSV 导入的账户是逐文件的**：`account_ids` 与 files 一一对应；只给 `account_id` 的旧调用整批共用并会自动改放。推荐顺序见 `imports._suggest_account`
- **「今天」一律取 `app.core.clock.local_today()`**：按 `TIMEZONE` 算，不用 `date.today()`——容器跑 UTC 时，日本早上 9 点前服务器还在前一天，预算会把整月当成已过完
- **预算的「已花」含一次性开支，预测不含**：预算管真实花出去的钱，预测只学习习惯（`services/budgets.py` 顶部有完整口径）。预测的纯计算函数 `forecast / judge / allocate` 不碰数据库，改算法先改 `tests/test_budgets.py`
- **整库备份只给实例所有者**（`User.is_owner` = 第一个用户）：备份里是所有用户的账目与密码哈希。新增任何「导出全部」类接口都要想清楚导出的是「我的」还是「整个库」
- **宽屏首页左栏常驻表单**：`TransactionForm` / `TransferForm` 的 `quick` 模式保存后只清金额与商家，日期、账户、方向保留。断点 1100px 同时写在 `lib/useMediaQuery.WIDE_QUERY` 与 `budget.css`，改一处要改两处
- **图表不引入库**：两张图是手写 SVG（`components/charts/`），颜色只用 CSS 令牌，深色模式自动跟随。新图沿用这个做法，公共零件在 `charts/chartUtils.tsx`（刻度、柱形、斜纹、指针换算）

