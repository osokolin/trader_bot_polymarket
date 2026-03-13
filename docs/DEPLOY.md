# Trader Bot Polymarket Deployment Guide

This document describes the current production deployment model for the
project. It is intentionally aligned with the live server setup:

- deploy from `main`
- run services as user `tg_bot`
- keep `semi_auto` strict
- keep live execution disabled
- use a project-local `.venv`
- store runtime config outside the repo

Repository: `git@github.com:osokolin/trader_bot_polymarket.git`

## 1. Server Requirements

Minimum:

- Ubuntu 24.04+ or another modern Linux distribution
- `git`
- `python3`
- `python3-venv`
- outbound HTTPS access to Telegram, GitHub, and Polymarket

Recommended:

- 2 vCPU
- 2 GB RAM
- 10 GB disk

## 2. Runtime Layout

Current recommended layout:

- code: `/home/tg_bot/apps/trader_bot_polymarket`
- runtime env: `/home/tg_bot/.config/trader_bot_polymarket.env`
- database: `/home/tg_bot/var/trader_bot/bot.db`
- update script: `/home/tg_bot/bin/trader-bot-update`

Do not store secrets in the git repository.

## 3. Initial Clone

```bash
git clone git@github.com:osokolin/trader_bot_polymarket.git ~/apps/trader_bot_polymarket
cd ~/apps/trader_bot_polymarket
python3 -m venv .venv
.venv/bin/pip install -e .
```

For local verification or development extras:

```bash
.venv/bin/pip install -e .[dev]
```

## 4. Runtime Configuration

Create:

`/home/tg_bot/.config/trader_bot_polymarket.env`

Example:

```bash
BOT_ENV=prod
BOT_MODE=semi_auto
BOT_DATABASE_URL=sqlite:////home/tg_bot/var/trader_bot/bot.db
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=143253216
BOT_UI_HOST=127.0.0.1
BOT_UI_PORT=8080
BOT_UI_SECURE_COOKIES=false
```

Notes:

- `BOT_MODE` must remain `semi_auto`
- `BOT_UI_SECURE_COOKIES=false` is acceptable only for localhost-only UI
  access through an SSH tunnel
- for public HTTPS deployment, switch `BOT_UI_SECURE_COOKIES=true`

## 5. Verification

Canonical project verification:

```bash
scripts/dev verify-fast
scripts/dev verify
```

Config validation:

```bash
.venv/bin/python -m bot.cli.app config validate
```

Diagnostics:

```bash
.venv/bin/python -m bot.cli.app diagnostics polymarket
```

## 6. Database and Migrations

The project uses SQLite and startup-applied migrations.

Fresh DB and upgrade flow both go through normal application startup.

Manual check:

```bash
sqlite3 /home/tg_bot/var/trader_bot/bot.db 'select version from schema_version;'
```

## 7. Setting the Web UI Password

The initial production username is configured by product decision, but the
password must be set outside source control.

Always load the runtime env first, otherwise the password may be written to
the wrong SQLite file.

```bash
cd ~/apps/trader_bot_polymarket
set -a
source ~/.config/trader_bot_polymarket.env
set +a
BOT_UI_PASSWORD='your-password-here' .venv/bin/python -m bot.cli.app auth set-password --username osokolin
```

## 8. Services

Recommended user-level services:

- `trader-bot-telegram.service`
- `trader-bot-ui.service`

Both should run from the project `.venv`, not the system interpreter.

Telegram:

```ini
ExecStart=/home/tg_bot/apps/trader_bot_polymarket/.venv/bin/python -m bot.cli.app telegram serve
```

UI:

```ini
ExecStart=/home/tg_bot/apps/trader_bot_polymarket/.venv/bin/python -m bot.cli.app ui serve --host 127.0.0.1 --port 8080
```

## 9. Updating Production

The canonical update path is:

1. `git fetch` / `git pull` on `main`
2. refresh `.venv` with `pip install -e .`
3. validate config
4. restart services

Example update script:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/apps/trader_bot_polymarket"
git fetch origin
current_branch=$(git branch --show-current)
if [ "$current_branch" != "main" ]; then
  git checkout main
fi
git pull --ff-only origin main
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -e .
set -a
source "$HOME/.config/trader_bot_polymarket.env"
set +a
.venv/bin/python -m bot.cli.app config validate >/dev/null
systemctl --user restart trader-bot-telegram.service
systemctl --user restart trader-bot-ui.service
systemctl --user is-active trader-bot-telegram.service >/dev/null
systemctl --user is-active trader-bot-ui.service >/dev/null
```

The GitHub Actions deploy workflow calls this script remotely after a
push to `main`.

## 10. Accessing the Web UI

Current safe production access model:

- UI binds to `127.0.0.1:8080` on the server
- no public UI port is opened
- operator connects through SSH tunnel

Example:

```bash
ssh -i ~/.ssh/id_ed25519 -L 8080:127.0.0.1:8080 tg_bot@148.253.209.168
```

Then open:

`http://127.0.0.1:8080/login`

## 11. Telegram Operator Interface

Start:

```bash
.venv/bin/python -m bot.cli.app telegram serve
```

Supported operator commands include:

- `/status`
- `/diagnostics`
- `/scan`
- `/inbox`
- `/review`
- `/review-next`

## 12. Safety Posture

The deployment must preserve:

- `semi_auto` strict
- live execution disabled
- no autonomous execution
- no order submission from Telegram or the web UI

## 13. Production HTTPS Later

If you later publish the web UI externally:

- add an HTTPS reverse proxy
- bind the app to localhost only
- set `BOT_UI_SECURE_COOKIES=true`
- prefer port `443`, not a raw public `8080`

## 14. Current Production Notes

The current server uses:

- SSH-based deploy from GitHub
- `~/bin/trader-bot-update` as the remote update entrypoint
- user-level systemd services under `tg_bot`
- localhost-only web access through SSH tunneling

This keeps the production surface small while preserving the current
single-operator workflow.
