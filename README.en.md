# Human Ledger

[中文](README.md) | [日本語](README.ja.md) | **English**

Keeping a budget is a good habit. Sticking with it is the hard part. Human Ledger tries to take the hard parts away.

It's a family budgeting web app you run on your own computer or server. It's built for people living in Japan and tracks everything in yen.

## What it solves

| Pain point | How Human Ledger handles it |
|------------|-----------------------------|
| Entering transactions one by one is tedious | Import statements from your bank, credit card or PayPay and record hundreds of transactions at once |
| Catching up on past spending is tedious | Import months or years of CSV exports in one go. Overlaps are removed automatically, so importing the same file twice never double-counts |
| Categorizing and analyzing every expense is tedious | A built-in dictionary of common Japanese merchants categorizes for you. Fix one transaction and the rest from the same merchant follow. Reports break spending down by trend, category and merchant |
| Keeping financial data in someone else's cloud feels risky | It runs on your own machine. Your data stays there and is never sent to a third party |
| Budgeting as a family is a hassle | Each family member signs up for their own account and gets a separate ledger, all on one server |

Supported statement formats: CSV exports from SMBC (三井住友銀行), SMBC Card (三井住友カード), Rakuten Card (楽天カード) and PayPay. You can also paste text from app screenshots. The interface is available in Chinese, Japanese and English.

## Getting started

Install [Docker](https://docs.docker.com/get-docker/) first.

```bash
git clone https://github.com/Ramirez0291/Human-Ledger.git
cd Human-Ledger
docker compose up -d
```

Then open `http://<this machine's IP>:8000` in a browser (or http://localhost:8000 on the same machine).

- The first person to open it sets up a username and password.
- Everyone else in the family uses "Sign up" at the same address and gets their own ledger.
- Any phone, tablet or computer that can reach the machine can use it from a browser.

**All data lives in the `data/` folder.** Back up that folder and you've backed up everything. You can also download a full backup from Settings → Backup & export in the app.

### Configuration

Copy `.env.example` to `.env`, edit it, then run `docker compose up -d` to apply.

- `ALLOW_REGISTRATION=false`: close sign-ups once the family is set up
- `PORT=8000`: change the host port
- `COOKIE_SECURE=true`: enable when serving over HTTPS

### Upgrading

```bash
git pull
docker compose up -d --build
```

The database schema is upgraded automatically on startup.

### Restoring from a backup

Put the backup zip in the `data/` folder, then:

```bash
docker compose stop
docker compose run --rm --entrypoint python -w /app/backend app scripts/restore_backup.py /app/data/your-backup.zip
docker compose start
```

Your previous data is kept as `*.bak-<timestamp>`.

## License

[GPL-3.0](LICENSE)
