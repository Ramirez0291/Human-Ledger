# Human Ledger

**中文** | [日本語](README.ja.md) | [English](README.en.md)

记账是个好习惯，但坚持下来太难。Human Ledger 想把难的部分都拿掉。

一个部署在你自己电脑或服务器上的家庭记账 Web 应用，以日元记账，面向在日本生活的人。

## 它解决什么

| 痛点 | Human Ledger 的做法 |
|------|----------------|
| 一笔一笔记太痛苦 | 直接导入银行、信用卡、PayPay 的明细，几百笔一次入账 |
| 补记以前的消费太痛苦 | 把过去几个月甚至几年的 CSV 导出一次性导进来；重叠的部分自动去重，重复导入也不会记两遍 |
| 给每笔支出分类、分析太痛苦 | 内置日本常见商家词典自动分类；改一笔，同一商家的其他笔跟着改；报表按趋势、分类、商家自动汇总 |
| 个人数据放在联网软件里太危险 | 自己部署，数据只存在你自己的机器上，不上传任何第三方 |
| 全家记账很麻烦 | 家人各自注册账号，每人一本独立账本，共用一台服务器 |

目前支持自动识别的明细格式：三井住友銀行、三井住友カード、楽天カード、PayPay 的 CSV；也可以把 App 截图上的文字粘贴进来导入。界面支持中文、日本語、English。

## 怎么用

需要先装好 [Docker](https://docs.docker.com/get-docker/)。

```bash
git clone https://github.com/Ramirez0291/Human-Ledger.git
cd Human-Ledger
docker compose up -d
```

启动后，用浏览器打开 `http://<这台机器的 IP>:8000`（本机就是 http://localhost:8000）。

- 第一个打开的人按提示设置用户名和密码。
- 家里其他人在同一个地址点「注册」，各自得到一本独立账本。
- 手机、平板、电脑，只要能访问这台机器，用浏览器就能记账。

**数据都在 `data/` 目录里**，备份这个目录就是备份整个账本。应用内「设置 → 备份与导出」也能下载完整备份。

### 常用配置

复制 `.env.example` 为 `.env` 修改后，执行 `docker compose up -d` 生效。

- `ALLOW_REGISTRATION=false`：家人都注册完后关闭注册
- `PORT=8000`：改对外端口
- `COOKIE_SECURE=true`：通过 HTTPS 访问时开启

### 升级

```bash
git pull
docker compose up -d --build
```

数据库结构会在启动时自动升级。

### 从备份恢复

把备份 zip 放进 `data/` 目录，然后：

```bash
docker compose stop
docker compose run --rm --entrypoint python -w /app/backend app scripts/restore_backup.py /app/data/备份文件名.zip
docker compose start
```

原有数据会被改名保留为 `*.bak-时间戳`。

## License

[GPL-3.0](LICENSE)
