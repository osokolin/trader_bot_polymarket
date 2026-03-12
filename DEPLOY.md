# Trader Bot Polymarket --- Deployment Guide

This document explains how to deploy and run the project in production
and verify the current functionality.

Repository: https://github.com/osokolin/trader_bot_polymarket

------------------------------------------------------------------------

# 1. Server Requirements

Minimum:

-   Linux (Ubuntu 22+ recommended)
-   Python 3.10+
-   git

Recommended:

-   2 vCPU
-   2 GB RAM
-   10 GB disk

For production:

-   nginx or Caddy
-   HTTPS

------------------------------------------------------------------------

# 2. Clone the Repository

git clone https://github.com/osokolin/trader_bot_polymarket.git cd
trader_bot_polymarket

Update later with:

git pull

------------------------------------------------------------------------

# 3. Create Python Environment

python3 -m venv .venv source .venv/bin/activate

Upgrade pip:

pip install -U pip

Install project:

pip install -e .\[dev\]

------------------------------------------------------------------------

# 4. Verify Environment

Run the canonical verification pipeline.

scripts/dev verify-fast

This runs:

-   pytest
-   ruff
-   mypy
-   py_compile

Expected result:

All checks passed

Full verification:

scripts/dev verify

This also runs:

-   config validation
-   demo seed

------------------------------------------------------------------------

# 5. Configuration

Validate configuration:

bot config validate

Expected:

config valid mode=semi_auto profile=balanced

Important:

mode must be `semi_auto`.

This guarantees:

-   no automatic execution
-   operator decisions required

------------------------------------------------------------------------

# 6. Database

Database used:

SQLite

After Milestone 4 the project uses migrations.

Initialize manually if needed:

python -c "from bot.storage.db import Database; Database().initialize()"

Database file created:

bot.db

Check schema version:

SELECT \* FROM schema_version;

Expected:

version = 1

------------------------------------------------------------------------

# 7. Seed Demo Data

To populate UI with example data:

bot demo seed

This creates:

-   proposals
-   alerts
-   reviews
-   probability snapshots

------------------------------------------------------------------------

# 8. Run Web Interface

Start UI:

bot ui

or

python -m bot.ui.app

Open:

http://localhost:8000

------------------------------------------------------------------------

# 9. Telegram Operator Interface

Set environment variable:

TELEGRAM_BOT_TOKEN

Run:

bot telegram run

Operator commands:

/review /review-next approve reject skip

------------------------------------------------------------------------

# 10. System Workflow

Current pipeline:

scanner → proposal bridge → policy checks → decision inbox → operator
review → execution intent (simulation)

Execution is NOT automatic.

------------------------------------------------------------------------

# 11. Decision Inbox

Check queue in UI:

/inbox

Or via Telegram:

/review

------------------------------------------------------------------------

# 12. Review Flow

Actions:

approve reject skip

These go through:

DecisionInboxService ProposalLifecycleService

------------------------------------------------------------------------

# 13. Diagnostics

Check Polymarket adapters:

bot diagnostics polymarket

Validates:

-   Gamma API
-   Polymarket client
-   market data

------------------------------------------------------------------------

# 14. Useful Commands

Quick verification:

scripts/dev verify-fast

Full verification:

scripts/dev verify

Validate configuration:

bot config validate

Seed demo data:

bot demo seed

------------------------------------------------------------------------

# 15. Production Reverse Proxy (nginx example)

server { listen 443 ssl; server_name trader.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }

}

HTTPS is strongly recommended.

------------------------------------------------------------------------

# 16. Systemd Service Example

File:

/etc/systemd/system/trader-web.service

\[Unit\] Description=Trader Web UI After=network.target

\[Service\] WorkingDirectory=/opt/trader_bot_polymarket
ExecStart=/opt/trader_bot_polymarket/.venv/bin/bot ui Restart=always
User=trader

\[Install\] WantedBy=multi-user.target

Enable service:

systemctl daemon-reload systemctl enable trader-web systemctl start
trader-web

------------------------------------------------------------------------

# 17. Backups

SQLite backup:

cp bot.db bot.db.backup

Recommended: nightly backups.

------------------------------------------------------------------------

# 18. Deployment Checklist

After deployment verify:

1.  verify-fast passes
2.  verify passes
3.  UI opens
4.  demo seed data visible
5.  inbox works
6.  migrations applied
7.  Telegram commands respond

------------------------------------------------------------------------

# 19. Current Limitations

Not implemented yet:

-   Strategy Engine
-   Risk Engine
-   Portfolio Console
-   Multi-user authentication
-   Automatic execution

------------------------------------------------------------------------

# 20. Next Planned Feature

Web authentication:

User: osokolin

Planned features:

-   session cookies
-   remember-browser tokens
-   revocable sessions
