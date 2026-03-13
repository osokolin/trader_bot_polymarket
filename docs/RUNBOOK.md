# Runbook

Operational guide for running the trading assistant.

---

# Services

Telegram bot:

trader-bot-telegram.service

Web UI:

trader-bot-ui.service

Check status:

systemctl --user status trader-bot-telegram
systemctl --user status trader-bot-ui

Restart:

systemctl --user restart trader-bot-telegram
systemctl --user restart trader-bot-ui

---

# Deployment

Deployment is triggered on push to main.

GitHub Actions:

SSH → server
run ~/bin/trader-bot-update

Manual deployment:

git pull
pip install -e .
systemctl --user restart trader-bot-telegram
systemctl --user restart trader-bot-ui

---

# Authentication

Set password:

bot auth set-password

Sessions use:

HttpOnly cookies
server-side sessions

Security page:

/auth/security

Allows revoking active sessions.

---

# Telegram Bot

Start runtime:

bot telegram serve

This enables:

- Telegram commands
- alert delivery
- background opportunity scanning

---

# Market Scanning

Manual:

bot alerts scan-opportunities
bot markets draft-opportunities

Telegram:

/scan-opportunities

---

# Diagnostics

Telegram:

/diagnostics

CLI:

bot diagnostics

---

# Common Issues

## Telegram bot not responding

systemctl --user status trader-bot-telegram

Logs:

journalctl --user -u trader-bot-telegram

## UI not accessible

systemctl --user status trader-bot-ui

SSH tunnel example:

ssh -L 8080:localhost:8080 server

---

# Backup

Important data stored in SQLite database.

Recommended:

- regular database backups
- config backups
- secrets backups
