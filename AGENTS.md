# AGENTS.md：给 AI 助手的安装、运行与使用说明

本文写给替用户安装、运行「人类账本」并教用户怎么用的 AI 助手，比如 Claude Code、Codex、Cursor。

先判断你在帮谁：

- 用户是来**改代码**的开发者：开发约定看 [README.md](README.md) 的「开发约定」。本文只有第 0 节的红线对你适用。
- 用户只是**想用这个记账软件**，多半不懂编程：照本文做。

跟这类用户说话时注意：

- 用用户的语言，少用术语。非说不可的术语，用一句话解释它是什么。
- 每做一步之前，先说要做什么、为什么做。
- 需要用户亲手做的事（点「允许」、输密码、在手机上导出账单），一次只交代一件，等用户做完再说下一件。
- 出错了先自己排查（第 8 节）。别把报错原样丢给用户。

---

## 0. 红线（任何时候都适用）

1. **`data/` 文件夹就是用户的全部账目。** 里面有三样东西：
   - `ledger.db`：账本本体。
   - `uploads/`：导入过的文件。
   - `.secret_key`：登录用的密钥。

   不删、不覆盖、不移动、不手动改。用户说「清空重来」时，先确认用户确实要丢掉全部账目，再把 `data/` 整个复制一份留底，然后才动它。
2. **忘记密码时不要删数据库重建。** 用 `scripts/reset_password.py`（第 8 节）。
3. **用户的账单文件含个人信息**：姓名、手机号、卡号尾号、每一笔消费。微信、支付宝、银行导出的 csv、xlsx 都算。
   - 不复制进项目文件夹，不提交到 git，不上传到任何第三方服务。
   - 不在回复里整段复述。
   - 导入是用户自己在网页上传。你一般不需要打开账单；需要排查格式问题时，只看表头和一两行，并告诉用户你在看什么。
4. **不把服务暴露到公网。** 不要用端口映射或内网穿透把 8000 端口开放到互联网，除非按第 6 节配好了 HTTPS 并关掉注册。
5. **升级、恢复备份、换电脑之前，先备份 `data/`。** 不要运行 `alembic downgrade`。
6. **装软件前先征得同意。** 装 Python、Node、Docker 之前，告诉用户要装什么、为什么要装、大概多大。同意了再装。
7. **账本地区建好后不能改。** 地区有「中国（人民币）」和「日本（日元）」两种，在初始化页面选定。同一个数字在两种币种下是两种金额，所以选定后不能改。初始化之前，先问清用户用哪国的钱记账。

---

## 1. 这是什么（向用户介绍时用）

人类账本是一个个人记账网页应用，跑在用户自己的电脑上。

- **数据只存在本机**，不上传到任何服务器。用浏览器打开 http://localhost:8000 使用。
- **中国账本**：导入微信支付账单和支付宝交易明细。程序会：
  - 按「支付方式」把每一笔分到零钱、余额、各张银行卡和信用卡；
  - 自动去掉重复的笔数；
  - 按商家自动分类，红包、外卖、打车、买菜等。
- **日本账本**：导入三井住友銀行、三井住友カード、楽天カード、PayPay 的 CSV。
- 都能手动记一笔、记转账。还有报表（趋势、分类占比、商家排行）、预算、导出 CSV 和整库备份。
- 界面有中文、日本語、English 三种语言。
- **截图识别还没做。** 暂时可以把截图上的文字复制下来，粘贴进「导入」页。

---

## 2. 选安装方式

| 用户的情况 | 用哪种 |
|---|---|
| 只在自己这台电脑上用（大多数人） | **A. 直接安装**（第 3 节） |
| 电脑上已经装好 Docker；或者要装在 NAS、家里常开的服务器上 | **B. Docker**（第 4 节） |

不要为了这个项目专门给个人电脑装 Docker Desktop，原因有两个：

- 在 Windows 上它要开 WSL2 并重启电脑，对新手负担大。
- 在中国大陆，Docker Hub 经常连不上。

---

## 3. 方式 A：直接安装

全程在**项目根目录**（本文件所在的文件夹）操作。

### 3.1 准备 Python 和 Node

- **Python 3.11 或更高。** 3.11 和 3.14 都完整验证过。
- **Node.js 20 或更高。** Node 只用来把网页界面构建一次（以后每次更新再构建一次），平时运行不需要。

**先检查**是否已经装了：

- Windows：`py --list`、`python --version`、`node --version`
- macOS / Linux：`python3 --version`、`node --version`

> Windows 的坑：`python` 可能指向 `...\Microsoft\WindowsApps\python.exe`。这只是微软商店的占位程序，要么什么都不输出，要么打开商店。遇到这种情况，当作没装 Python。

**没有就装**（先征得用户同意）：

- **Windows**：用 winget。安装 Node 时会弹出 Windows 的权限确认，请用户点「是」。

  ```powershell
  winget install -e --id Python.Python.3.14 --accept-source-agreements --accept-package-agreements
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  ```

  装完后，当前终端还找不到新命令。刷新一下 PATH：

  ```powershell
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  ```

- **macOS**：
  - 有 Homebrew（`brew --version` 能运行）时：`brew install python@3.13 node`
  - 没有 Homebrew 时：请用户从 python.org 和 nodejs.org 下载安装包，双击安装。

- **Linux（Debian / Ubuntu）**：`sudo apt install python3 python3-venv`。
  - 系统源里的 Node 往往太旧，用 nvm 或 NodeSource 装 20 以上的版本。

### 3.2 安装依赖并构建网页界面

**Windows（PowerShell）：**

```powershell
cd backend
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m alembic upgrade head
cd ..\frontend
npm ci
npm run build
cd ..
```

没有 `py` 命令时，把第二行换成 `python -m venv .venv`。

**macOS / Linux：**

```sh
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m alembic upgrade head
cd ../frontend
npm ci
npm run build
cd ..
```

几点说明：

- **不要激活虚拟环境**，直接调用 `.venv` 里的 python。Windows 的 PowerShell 默认禁止运行 `Activate.ps1`。
- **不需要 `.env` 文件。** 本机自用时全部用默认值就行；登录密钥会自动生成，存进 `data/.secret_key`。
- `npm ci` 可能提示 `install-scripts ... esbuild`。这是正常提示，不影响构建。
- **中国大陆下载慢或失败时，换国内镜像：**
  - pip 加 `-i https://mirrors.aliyun.com/pypi/simple/`
  - npm 用 `npm ci --registry=https://registry.npmmirror.com`

### 3.3 启动，并确认真的跑起来了

**给用户用的启动方式**：

- Windows：双击 `start-windows.bat`。
- macOS：第一次先运行 `chmod +x start-mac.command`，之后双击 `start-mac.command`。
- Linux：`sh start-mac.command`。

启动脚本会依次做这几件事：

1. 如果账本已经在运行，就只打开浏览器。
2. 否则先升级数据库结构（更新代码后必须做这一步，平时做也不碍事）。
3. 在 http://localhost:8000 启动服务。
4. 等服务就绪后自动打开浏览器。

**那个命令行窗口就是账本服务本身，关掉窗口账本就停了。** 一定要告诉用户这一点。

**你自己验证时**，不要用双击脚本（它会一直占着终端）：

1. 在后台从 `backend/` 目录启动服务：
   - Windows：`.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
   - macOS / Linux：`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. 检查两件事：
   - `http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`。
   - `http://127.0.0.1:8000/` 返回的是网页，内容里有 `id="root"`。如果返回的是一段 JSON，写着「前端尚未构建」，说明 `npm run build` 没成功。
3. 验证完停掉你启动的这个进程。然后让用户双击启动脚本，自己走一遍以后每天要做的流程。

第一次启动可能要十几秒，之后几秒就好。

### 3.4 放一个桌面快捷方式（推荐）

**Windows**：在桌面放一个转发用的 `人类账本.bat`。在项目根目录运行：

```powershell
$root = (Get-Location).Path
$desk = [Environment]::GetFolderPath('Desktop')
$text = "@echo off`r`nchcp 65001 >nul`r`ncall `"$root\start-windows.bat`"`r`n"
[IO.File]::WriteAllText((Join-Path $desk '人类账本.bat'), $text, (New-Object Text.UTF8Encoding $false))
```

这里有两个坑，别换成看起来更常规的写法：

- **不要用 `WScript.Shell` 建 `.lnk` 快捷方式。** 路径里有系统代码页以外的字时，它会报错或把字变成问号。比如日文 Windows 遇到「人类账本」里的「类」「账」。
- **文件必须是不带 BOM 的 UTF-8。** PowerShell 5.1 的 `Set-Content`、`Out-File` 会写入 BOM，导致第一行失效。

想开机自动启动的话，把 `'Desktop'` 换成 `'Startup'` 再运行一次。开机后会多一个命令行窗口，提前告诉用户。

**macOS**：不能用替身或软链接，否则脚本找不到项目文件夹。在桌面放一个转发脚本：

```sh
printf '#!/bin/sh\nexec "%s/start-mac.command"\n' "$PWD" > ~/Desktop/人类账本.command && chmod +x ~/Desktop/人类账本.command
```

装好以后，接着带用户做第 7.1 节的初始化。

---

## 4. 方式 B：Docker

```sh
cp .env.example .env
```

编辑 `.env`，至少改这几项：

| 项 | 值 |
|---|---|
| `SECRET_KEY` | 用 `python -c "import secrets;print(secrets.token_urlsafe(48))"` 生成。生产模式下留空会拒绝启动 |
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `ALLOW_REGISTRATION` | 只有一个人用时设为 `false`，见下面的说明 |
| 中国用户 | `DEFAULT_LOCALE=zh-CN`、`DEFAULT_REGION=CN`、`TIMEZONE=Asia/Shanghai` |

关于 `ALLOW_REGISTRATION=false`：它只关掉「注册」入口，第一次打开时的初始化不受影响。家人要各记各的账时，保持 `true`，让他们各自注册（每个人的账目互相看不到）。

启动并检查：

```sh
docker compose up -d --build
docker compose ps
```

几分钟后状态显示 `healthy` 就是好了。再访问 `http://127.0.0.1:8000/api/health` 确认一下。

- 数据在宿主机的 `./data` 里（挂载到容器内）。容器删了重建，数据也还在。
- 容器每次启动都会自动升级数据库结构。
- 在中国大陆构建失败时：先在 Docker 设置里配置镜像加速。构建过程中 pip 和 npm 也要下载依赖，网络不通会失败。

---

## 5. 日常维护

**启动**

- 方式 A：双击启动脚本，或桌面快捷方式。
- 方式 B：`docker compose up -d`。

**停止**

- 方式 A：关掉命令行窗口，或在窗口里按 Ctrl+C。
- 方式 B：`docker compose down`。数据不会丢。

**备份**（每月一次，或者导入大量数据之前）

- **网页里**：「设置」→「备份与导出」→「下载完整备份」。只有第一个创建的用户（管理员）能下载整库备份。
- **直接复制**：先停掉服务，再把 `data/` 整个文件夹复制到别处。

**从备份恢复**

1. 先停掉服务。
2. 在 `backend/` 目录运行：`.venv\Scripts\python.exe scripts/restore_backup.py <备份zip路径>`（macOS / Linux 用 `.venv/bin/python`）。

现有数据会先改名为 `*.bak-时间戳`，留在原处。

**更新到新版本**

1. 停掉服务，备份 `data/`。
2. 拿到新代码：
   - 项目是 git 克隆的：`git pull`。
   - 是下载的压缩包：解压到新文件夹，把旧文件夹里的 `data/` 复制过去。有 `.env` 的话也一起复制。新包里没有 `data/`，不会覆盖用户数据。
3. 重新安装依赖并构建：
   - 方式 A：重做 3.2 的 `pip install`、`npm ci`、`npm run build` 三步。数据库结构由启动脚本自动升级。
   - 方式 B：`docker compose up -d --build`。

**换电脑**

1. 在新电脑上按第 3 节装好。
2. 先**不要**打开网页做初始化。
3. 把旧电脑的 `data/` 复制过来，再启动。

注意：`backend/.venv` 和 `frontend/node_modules` 不能跨电脑复制，必须在新电脑上重装。

---

## 6. 用手机访问；放到公网

**同一个 Wi-Fi 下用手机访问**：

1. 在项目根目录建一个 `.env` 文件，写一行 `ALLOW_REGISTRATION=false`。否则同一网络里的任何人都能在这个账本上注册账号。
2. 把启动脚本里的 `HOST=127.0.0.1` 改成 `HOST=0.0.0.0`，然后重启。
3. Windows 第一次会弹出防火墙提示，请用户勾选「专用网络」并点「允许」。
4. 查电脑的局域网 IP：
   - Windows：`ipconfig`，看 IPv4 地址。
   - macOS：`ipconfig getifaddr en0`。
5. 手机浏览器打开 `http://<这个IP>:8000`。

这种方式没有加密。在家里的 Wi-Fi 下可以用，在咖啡馆等公共 Wi-Fi 下不要开。

**放到公网**：除非用户懂运维，否则不建议。必须做的有：

- 用反向代理（如 Caddy）加 HTTPS。
- `.env` 里设 `COOKIE_SECURE=true`、`APP_ENV=production`、`SECRET_KEY`、`ALLOW_REGISTRATION=false`。

更省事的办法是用组网工具（如 Tailscale）只让自己的设备连进来。

---

## 7. 教用户使用

一步一步带，不要一次讲完。先完成 7.1 和 7.2（或 7.3），用户看到自己的账目出现了，再按兴趣介绍其他功能。界面上的菜单有：总览、流水、账户、导入、报表、预算、设置。

### 7.1 第一次打开：初始化

浏览器打开后是「初始化」页面，要填：

| 项 | 怎么填 |
|---|---|
| 用户名、密码 | 密码至少 8 位，请用户自己记住。目前网页里没有「改密码」功能，忘了只能用第 8 节的脚本重设 |
| 界面语言 | 中文 / 日本語 / English，之后可以改 |
| **账本地区** | 「中国（人民币）」或「日本（日元）」。**之后不能改**，先跟用户确认 |

### 7.2 中国账本：导入微信和支付宝账单

**第 1 步：在手机上导出账单**（用户自己操作）。两种账单都会以压缩包形式发到用户填的邮箱。解压密码会发到手机上，请用户按 App 的提示查看。系统自带的解压工具打不开时，可以用 7-Zip 或 Bandizip。

- **微信**：我 → 服务 → 钱包 → 账单 → 常见问题 → 下载账单 → 用于个人对账 → 选时间范围、填邮箱。解压后是 xlsx 或 csv 文件。
- **支付宝**：我的 → 账单 → 右上角「…」→ 开具交易流水证明 → 用于个人对账 → 选时间范围、填邮箱。解压后是 csv 文件。

**第 2 步：在网页上导入。**

1. 打开「导入」，导入来源选「CSV 文件」，选择解压出来的文件。可以一次多选，微信和支付宝的文件一起选也行。
2. 预览里会出现「支付方式 → 账户」，列出账单里出现过的零钱、余额、某银行卡(尾号)、花呗等，以及每种对应到哪个账户。第一次导入保持默认就好：没有对应账户的，会按原名自动新建。
3. 点「导入 N 行」。

**第 3 步：在「待确认」里核对，然后入账。**

- 每一行是一笔交易，勾选的行才会入账。
- 「已跳过 N 行」里列出了不入账的行和原因，比如交易关闭、0 元占位、支付失败、已经在账本里。导入后金额对不上时，先看这里。
- 标着「可能重复」的行，请用户看一眼再决定。
- 改一行的类目时，同一批里同一商家的行会跟着一起改。确认入账后系统会记住，下次这家商家自动用这个类目。
- 核对完点「入账 N 笔」。

**之后：**

- 到「账户」页给自动建的账户改名，并填「期初余额」，也就是开始记账那天账户里有多少钱。信用卡填当时还欠多少钱，用负数。
- 以后每隔一段时间导出新账单再导入就行。时间段和上次重叠也没关系，重复的会自动跳过。
- 先导微信还是先导支付宝都可以。同一张银行卡在两份账单里会对应到同一个账户。
- 导错了：「导入」页下方的「导入记录」里可以「撤销整批」。

### 7.3 日本账本：导入银行和信用卡的 CSV

- 这几家的 CSV 会自动识别：三井住友銀行口座明細、三井住友カード、楽天カード（e-NAVI）、PayPay 取引履歴。
- 其他银行的 CSV，导入时需要指定每一列是什么意思（日期、金额、商家……）。
- 先在「账户」页建好对应的账户，导入时选对账户。选错了的话，重复的笔数会认不出来。
- 后面的核对和入账流程与 7.2 相同。

### 7.4 其他功能（按需介绍）

- **记一笔**：手动记现金之类的支出和收入。
- **转账**：信用卡还款、零钱充值或提现、转入余额宝或零钱通、取现，都要记成「转账」，不能记成支出，否则同一笔钱会被算两次。导入账单时，程序认得出的转账会自动处理。
- **报表**：收支趋势、分类占比（点进去能看小类）、商家排行、每日支出、大额支出。一次性的大额开支在「大额支出」里关掉开关，就不再算进日常开支。
- **预算**：「设置预算」→「按过去的习惯填入」，看过、改过再保存。节假日出游这类开销，可以加一笔「特别预算」。
- **设置**里还有：
  - **记账风格**：「轻松」（推荐）允许漏记，余额以最近一次填的真实余额为准；「合规模式」要求每一分钱都对得上。
  - 类目管理、分类规则：比如「包含 spotify 的都归到订阅」。
  - 备份与导出。
- **回收站**：在「流水」页。删掉的交易可以在这里恢复。

---

## 8. 故障排查

| 现象 | 处理 |
|---|---|
| 启动窗口报 `address already in use` 或 `[WinError 10048]` | 8000 端口被别的程序占用了。把启动脚本里的 `PORT=8000` 改成 `8001` 之类，以后就用新地址访问 |
| 打开网页只显示一段 JSON，写着「前端尚未构建」 | 在 `frontend/` 里重新运行 `npm run build`，看哪里报错 |
| 启动时报数据库升级失败 | 先备份 `data/`，再把完整报错读一遍。报错里有 `alembic.ini` 和编码字样时，说明有人往 `backend/alembic.ini` 里写了非 ASCII 字符（比如中文注释），把它还原 |
| 每次重启都要重新登录 | `data/.secret_key` 写不进去，或者 `.env` 里的 `SECRET_KEY` 变了。检查 `data/` 的写权限 |
| **忘记密码** | 在 `backend/` 目录运行 `.venv\Scripts\python.exe scripts/reset_password.py <用户名>`（macOS / Linux 用 `.venv/bin/python`），把打印出来的新密码告诉用户。网页里目前没有改密码功能，请用户把新密码存进密码管理器或记下来 |
| 忘记用户名 | 同一个脚本不带参数运行，会列出所有用户名 |
| 导入时提示文件币种和账本不符 | 微信、支付宝账单只能导进「中国」账本。账本地区建错了只能新注册一个用户，第 0 节第 7 条说明了原因 |
| macOS 提示「无法打开，因为它来自身份不明的开发者」 | 运行 `xattr -d com.apple.quarantine start-mac.command`，或者右键这个文件 →「打开」 |
| Windows 双击 `.bat` 弹出「Windows 已保护你的电脑」 | 点「更多信息」→「仍要运行」。项目来自压缩包时常见 |
| `pip install` 或 `npm ci` 很慢、连接超时 | 换国内镜像，见 3.2 |

解决不了时，请用户把启动窗口里的全部文字复制给你。别让用户自己去猜。

---

## 9. 文件速查

| 路径 | 是什么 |
|---|---|
| `start-windows.bat` / `start-mac.command` | 一键启动脚本 |
| `data/` | **全部数据，唯一需要备份的东西** |
| `.env` | 可选配置，说明见 `.env.example` |
| `backend/` | 服务端（Python）。`backend/.venv` 是装好的依赖，删了可以重装 |
| `backend/scripts/` | 维护脚本：`reset_password.py`、`restore_backup.py`、`inspect_db.py` |
| `frontend/` | 网页界面的源代码。`frontend/dist` 是构建好的网页，删了可以重新构建 |
| `docs/requirements.md` | 详细需求，以及各种账单格式的说明（附录 C 是微信，附录 D 是支付宝） |
