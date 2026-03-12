# OPERATOR.md

# Trader Bot Polymarket — Operator Guide

This guide explains:

- what to configure before running the system
- where each key and setting lives
- what each subsystem is responsible for
- how to inspect markets, proposals, alerts, reviews, and simulations
- how to make operator decisions safely in `semi_auto` mode
- what to verify on production before relying on the tool

Repository:
`https://github.com/osokolin/trader_bot_polymarket`

---

# 1. What this system is

This project is a **policy-first, semi-automatic operator assistant** for Polymarket-style workflows.

Current design goals:

- **policy-first**
- **configuration-first**
- **semi_auto by default**
- **live execution disabled**
- **no autonomous execution**

In practice, that means the system can:

- collect public market data
- build candidate proposals
- apply policy checks
- persist proposals, reviews, and simulation records
- expose state through CLI, dashboard UI, and Telegram operator inbox

But it still expects a **human operator** to review and decide.

---

# 2. High-level operating flow

Current flow:

1. Market snapshot + signal + probability input are combined
2. Sizing logic proposes a candidate trade shape
3. Composite policy checks decide whether the candidate may proceed
4. Proposal is stored in SQLite
5. In `semi_auto`, proposals wait for human review
6. Operator may inspect, approve, reject, cancel, or skip depending on interface/workflow
7. Approval triggers revalidation before progressing
8. All important transitions are written to audit/review history

Think of the system as an **operator console with policy enforcement**, not an autonomous trader.

---

# 3. Where configuration lives

There are **two main places** to configure the system:

## A. Environment variables

Use `.env` or service-level environment configuration.

Start from:

`/.env.example`

Current keys in `.env.example`:

- `BOT_ENV`
- `BOT_MODE`
- `BOT_DATABASE_URL`
- `BOT_UI_HOST`
- `BOT_UI_PORT`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`

## B. YAML policy/config files

Runtime rules live in:

`/config/`

Current config files visible in the repo:

- `base.yaml`
- `balanced.yaml`
- `aggressive.yaml`
- `conservative.yaml`
- `blacklist.yaml`
- `whitelist.yaml`
- `sources.yaml`

Use these files for operating policy and risk posture, not for secrets.

---

# 4. What each environment variable does

## `BOT_ENV`

Purpose:
Selects the deployment environment label.

Typical value:
`dev`

Use on prod:
Set something explicit such as `prod` or `production` if your deployment conventions expect that.

## `BOT_MODE`

Purpose:
Overrides the operating mode.

Important values mentioned in config/docs:

- `paper`
- `manual_only`
- `semi_auto`
- `live_small`
- `live_full`

Recommended production value right now:
`semi_auto`

Why:
This keeps manual approval in the loop and aligns with the current architecture and workflow.

## `BOT_DATABASE_URL`

Purpose:
Points CLI/UI runtime to the SQLite database file.

Example:
`sqlite:///bot.db`

Production recommendation:
Use an absolute path in persistent storage, for example:

`sqlite:////var/lib/trader_bot_polymarket/bot.db`

## `BOT_UI_HOST`

Purpose:
Host/IP address for the dashboard web server.

Examples:
- local only: `127.0.0.1`
- behind reverse proxy on same machine: `127.0.0.1`

Production recommendation:
Bind to `127.0.0.1` and expose externally only through nginx/Caddy.

## `BOT_UI_PORT`

Purpose:
Port for the dashboard web server.

Default example:
`8080`

## `TELEGRAM_BOT_TOKEN`

Purpose:
Bot token for Telegram operator inbox.

How to get it:
Create a bot with BotFather and paste the token here.

Security:
Treat it like a secret. Do not commit it.

## `TELEGRAM_ALLOWED_CHAT_IDS`

Purpose:
Comma-separated list of Telegram chat IDs allowed to interact with the operator inbox.

Example:
`123456789,987654321`

Important:
Do not leave this wide open in production.

---

# 5. What each YAML config file does

## `config/base.yaml`

This is the core operating policy.

It defines the baseline for:

- mode
- bankroll sizing inputs
- reserve ratio
- daily/weekly loss caps
- position limits
- market filters
- entry rules
- approval requirements
- policy-related defaults

This is the most important file for the operator.

## `config/balanced.yaml`

Intended as the default moderate-risk profile layered on top of base config.

Use when:
You want the normal default operating posture.

## `config/conservative.yaml`

Tighter posture.

Use when:
- you are testing in production carefully
- you want fewer proposals
- you want smaller and stricter selection

## `config/aggressive.yaml`

Looser posture.

Use when:
- you are experimenting in paper/demo environments
- you are deliberately widening candidate flow

Do not use casually on prod without understanding the policy impact.

## `config/blacklist.yaml`

Use to block things that should never be considered.

Typical usage:
- categories
- patterns
- banned markets/themes

## `config/whitelist.yaml`

Use to explicitly allow certain categories/themes/markets.

Typical usage:
- narrowing operation to a known set of areas

## `config/sources.yaml`

Trusted source domains.

Used to express source trust policy for proposals/research logic.

---

# 6. How to think about the most important config knobs

## Mode

`mode` is the top-level safety dial.

Recommended now:
`semi_auto`

Why:
The project is explicitly built around semi-automatic operation, manual approval, and no autonomous execution.

## Bankroll

Key section:
`bankroll.*`

What it controls:
- base capital for sizing
- reserve left untouched
- max daily loss
- max weekly loss

Operator meaning:
This is your **risk budget**. If you set it too high, all downstream size suggestions become more permissive.

## Position limits

Key section:
`position_limits.*`

What it controls:
- max size per position
- max exposure by theme/event cluster
- max number of open positions
- max unresolved exposure

Operator meaning:
This is your **concentration control**.

## Market filters

Key section:
`market_filters.*`

What it controls:
- allowed categories
- blocked categories
- min liquidity
- max spread
- min time to resolution
- whether clear rules/orderbook are required

Operator meaning:
This is your **market quality filter**.

## Entry rules

Key section:
`entry_rules.*`

What it controls:
- minimum edge
- minimum confidence
- model agreement
- trusted-source requirements
- order type restrictions

Operator meaning:
This is your **signal quality threshold**.

---

# 7. Suggested production starting values

If you are deploying now and want to test safely:

- mode: `semi_auto`
- profile: `balanced` or even `conservative`
- database: persistent SQLite path
- UI host: `127.0.0.1`
- UI port: `8080`
- Telegram allowed chat IDs: explicitly restricted
- use demo seed first, then real diagnostics/inspection

Conservative production-first testing is better than widening candidate flow too early.

---

# 8. Database and persistence

Storage backend:
SQLite

Important behavior:
- the app initializes schema automatically
- schema evolution is migration-based
- proposal, audit, review, alert, and snapshot state is persisted

What this means operationally:
- state survives restarts
- UI/CLI/Telegram all read from the same persisted operator history
- backups matter

Recommended production DB path:
`/var/lib/trader_bot_polymarket/bot.db`

Recommended backup approach:
Nightly copy/snapshot of the SQLite database file.

---

# 9. What the major subsystems are responsible for

## CLI

Purpose:
Direct operator control and inspection from shell.

Use it for:
- verification
- config validation
- seeding demo data
- listing proposals/intents/alerts
- diagnostics
- portfolio and analysis views

## Web UI

Purpose:
Dashboard and browser-based operator inspection.

Use it for:
- dashboard overview
- proposal detail
- alerts
- research/probability snapshots
- market data inspection
- decision review pages
- saved views and exports

Important current limitation:
Web auth is not yet implemented in the repository baseline described here, so do not expose the UI publicly without network-layer protection.

## Telegram Operator Inbox

Purpose:
Fast operator review surface.

Use it for:
- status
- diagnostics
- inbox browsing
- request review queue
- proposal review actions

This is meant to stay thin: it is an operator interface, not a place for hidden business logic.

## Policies

Purpose:
Decide whether a candidate may proceed.

Policies enforce:
- market quality requirements
- source trust requirements
- size/risk constraints
- operating boundaries

## Proposal lifecycle

Purpose:
Own proposal state transitions.

Important operator consequence:
A proposal is not just “approved or rejected”; its transitions are controlled and audited.

## Reviews and simulations

Purpose:
Support operator learning and dry-run analysis.

Use them for:
- checking decision quality
- inspecting simulated execution
- understanding slippage and outcomes
- reviewing the audit trail

---

# 10. Initial production setup checklist

## Step 1 — clone and install

```bash
git clone https://github.com/osokolin/trader_bot_polymarket.git
cd trader_bot_polymarket
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

## Step 2 — create environment file

```bash
cp .env.example .env
```

Then edit `.env`.

Minimal safe starting point:

```dotenv
BOT_ENV=prod
BOT_MODE=semi_auto
BOT_DATABASE_URL=sqlite:////var/lib/trader_bot_polymarket/bot.db
BOT_UI_HOST=127.0.0.1
BOT_UI_PORT=8080
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
```

## Step 3 — validate config

```bash
.venv/bin/bot config validate
```

## Step 4 — run verification

```bash
scripts/dev verify-fast
scripts/dev verify
```

## Step 5 — seed demo data for first smoke test

```bash
.venv/bin/bot demo seed
```

## Step 6 — start UI

```bash
.venv/bin/bot ui serve --host 127.0.0.1 --port 8080
```

## Step 7 — optionally start Telegram inbox

```bash
.venv/bin/bot telegram serve
```

---

# 11. Day-to-day operator commands

## Verify environment

```bash
scripts/dev verify-fast
scripts/dev verify
```

## Validate config

```bash
.venv/bin/bot config validate
```

## Seed demo data

```bash
.venv/bin/bot demo seed
```

## Inspect proposals

```bash
.venv/bin/bot proposals list --scope active
.venv/bin/bot proposals latest-approved
.venv/bin/bot proposals decision-review <proposal_id>
```

## Inspect intents and simulations

```bash
.venv/bin/bot intents list --scope terminal
.venv/bin/bot intents latest-simulated
```

## Inspect alerts

```bash
.venv/bin/bot alerts list --state open
```

## Inspect markets

```bash
.venv/bin/bot markets live <market_id>
.venv/bin/bot markets cache <market_id>
.venv/bin/bot markets stream-once <market_id>
```

## Inspect analytics / portfolio

```bash
.venv/bin/bot analysis outcomes --group-by market
.venv/bin/bot portfolio summary
```

## Start UI

```bash
.venv/bin/bot ui serve --host 127.0.0.1 --port 8080
```

## Start Telegram operator inbox

```bash
.venv/bin/bot telegram serve
```

---

# 12. Telegram operator usage

Supported commands visible in the repository docs include:

- `/start`
- `/help`
- `/status`
- `/diagnostics`
- `/scan`
- `/inbox`
- `/review`
- `/review-next`
- `/request <id>`
- `/proposals`
- `/proposal <id>`
- `/approve <id>`
- `/reject <id>`
- `/cancel <id>`

Operational meaning:

- `/status` — quick system sanity view
- `/diagnostics` — adapter/runtime checks
- `/inbox` — inspect request list
- `/review` — show open review queue
- `/review-next` — jump to next open request
- `/request <id>` — inspect a specific request
- `/approve` / `/reject` / `/cancel` — operator actions on proposals/requests where supported

Keep Telegram access restricted to approved chat IDs.

---

# 13. Web UI usage

Start:

```bash
.venv/bin/bot ui serve --host 127.0.0.1 --port 8080
```

Then open:
`http://127.0.0.1:8080`

Available UI areas documented in the repository include:

- dashboard home
- proposals and intents
- alerts with acknowledge/dismiss/resolve actions
- research and probability snapshots
- live market data inspection
- integrated decision review pages
- outcome analysis
- saved views
- export pages

Recommended smoke-test path:

1. Open dashboard
2. Confirm summary cards render
3. Open an approved proposal
4. Inspect live market data for its market
5. Open integrated decision review
6. Inspect latest execution evaluation
7. Open saved views
8. Open export pages

---

# 14. How to make operator decisions

This is the most important section.

## First principle: do not treat proposals as orders

A proposal is a **candidate** shaped by sizing and policy.
It is not a command to trade blindly.

## Second principle: keep `semi_auto` strict

Until authentication and broader production controls are in place, keep operation in `semi_auto` and preserve manual approval.

## Third principle: review the full context, not one number

Before approving a proposal, check:

- market identity and rules clarity
- liquidity
- spread quality
- time to resolution
- category/theme concentration
- confidence and edge assumptions
- whether the proposal still fits current bankroll/risk posture
- whether there are already overlapping open positions or unresolved exposure

## Fourth principle: use conservative overrides first

If a proposal is directionally interesting but too large or too close to limits:

- reduce size
- tighten acceptable price
- defer instead of forcing approval
- reject if policy concerns are material

## Fifth principle: trust revalidation

Approval triggers revalidation.
If revalidation fails, the move to `policy_rejected` is a safety feature, not an inconvenience.

---

# 15. Practical approve / reject framework

## Approve when all of the following are true

- the market is understandable and rules are clear
- liquidity and spread are acceptable
- the category is allowed
- proposal size is reasonable for current bankroll
- confidence/edge are not obviously stale or weak
- the position does not overload theme or unresolved exposure
- you are comfortable defending the trade in a later review

## Reject when any of the following are true

- unclear or ambiguous market rules
- low liquidity / poor spread
- too close to resolution
- confidence or rationale feels weak
- category/theme should not be traded
- proposal conflicts with current exposure
- proposal only looks attractive because the profile is too loose

## Cancel / skip when appropriate

Use skip/cancel-like flows when:
- the request is acknowledged but not actionable now
- you need to move through the queue without treating it as an approval
- the proposal is stale, superseded, or no longer worth attention

---

# 16. What to watch during production testing

During initial prod testing, watch:

- does config validation pass cleanly?
- does the UI start reliably?
- does demo seed populate visible state?
- do diagnostics succeed?
- does Telegram only respond to approved chat IDs?
- are proposals and requests persisted across restart?
- does review history remain intact?
- do migrations apply automatically on first start?

If any of those fail, stop and fix them before using the system operationally.

---

# 17. Recommended prod topology

Recommended shape:

- app process bound to `127.0.0.1:8080`
- reverse proxy in front (nginx or Caddy)
- SQLite on persistent local storage
- optional separate service for Telegram
- `.env` managed outside source control
- regular DB backups

Important:
Because web auth is not yet in place, do not expose the UI directly to the public internet without additional access control.

---

# 18. Logging and troubleshooting

## Validate config first

```bash
.venv/bin/bot config validate
```

## Re-run verification

```bash
scripts/dev verify-fast
```

## If UI is empty

Run:

```bash
.venv/bin/bot demo seed
```

Then refresh the UI.

## If Telegram does not respond

Check:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- whether the service process is running
- whether the bot is started with the correct environment

## If data seems missing after restart

Check:
- `BOT_DATABASE_URL`
- file permissions for the DB path
- whether you accidentally pointed prod and test runs at different SQLite files

---

# 19. What is not in scope yet

Current repo baseline does **not** yet provide:

- web authentication
- multi-user access control
- autonomous live trading
- full strategy engine
- separate risk engine
- portfolio console as a first-class dedicated subsystem

Plan operations accordingly.

---

# 20. Recommended operator habits

Use this routine:

## Before the day starts
- validate config
- confirm mode is `semi_auto`
- check dashboard and alerts
- review open requests
- confirm DB path is correct
- confirm Telegram access is restricted

## During the day
- work from inbox/review queue
- inspect proposal context before acting
- prefer conservative sizing changes
- use diagnostics when market data looks suspicious
- avoid forcing approvals on stale proposals

## After sessions
- review terminal intents and simulated executions
- inspect decision reviews
- review outcome analysis
- back up the database

---

# 21. Minimal production-ready operator checklist

Use this as the short version:

- `.env` created and not committed
- `BOT_MODE=semi_auto`
- `BOT_DATABASE_URL` points to persistent storage
- UI bound to localhost only
- reverse proxy in front
- Telegram token set
- allowed chat IDs restricted
- `bot config validate` passes
- `scripts/dev verify` passes
- `bot demo seed` works
- UI and Telegram both show expected state

If all of that is true, you are ready to connect the current system on prod and test the existing functionality safely.
