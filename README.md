# Polymarket AI Bot

Policy-first, semi-automatic operator assistant for Polymarket-style trading workflows.

Current defaults remain strict:
- `architecture: policy-first`
- `mode: semi_auto`
- live execution disabled
- no autonomous execution

The repository currently includes:
- proposal generation and policy gating
- proposal lifecycle with approval, edits, rejection, TTL expiry, and revalidation
- public Polymarket Gamma/CLOB market-data adapters plus market snapshot cache
- persisted order intents and simulation-only execution pipeline
- paper execution, decision review, execution evaluation, outcome analysis
- CLI operator tooling
- lightweight operator dashboard UI

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md), [docs/CONFIG_REFERENCE.md](./docs/CONFIG_REFERENCE.md), and [docs/SEMI_AUTO_WORKFLOW.md](./docs/SEMI_AUTO_WORKFLOW.md).

## Local Setup

Requirements:
- Python 3.12+

Install:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Optional local env file:

```bash
cp .env.example .env
```

Validate config:

```bash
.venv/bin/bot config validate
```

Module entrypoint also works:

```bash
.venv/bin/python -m bot.cli.app config validate
```

Use an isolated local database for smoke/demo runs:

```bash
export BOT_DATABASE_URL=sqlite:///bot.db
```

## CLI Usage

Common commands:

```bash
bot proposals list --scope active
bot proposals latest-approved
bot proposals decision-review <proposal_id>
bot intents list --scope terminal
bot intents latest-simulated
bot alerts list --state open
bot markets live <market_id>
bot markets cache <market_id>
bot markets stream-once <market_id>
bot analysis outcomes --group-by market
bot portfolio summary
```

Seed local demo data for operator testing:

```bash
.venv/bin/bot demo seed
```

This populates the local `bot.db` with:
- pending and approved proposals
- prepared and simulated intents
- alerts and watchlist state
- decision review snapshots
- execution evaluation snapshots
- outcome analysis snapshots
- a couple of saved views

## UI Usage

Start the operator dashboard:

```bash
.venv/bin/bot ui serve --host 127.0.0.1 --port 8080
```

Then open:

```text
http://127.0.0.1:8080
```

Available UI areas:
- dashboard home
- proposals and intents
- alerts with acknowledge/dismiss/resolve actions
- research and probability snapshots
- live market data inspection
- integrated decision review pages
- outcome analysis
- saved views
- export pages for decision reviews, execution evaluations, and outcome analysis

## UI Screenshots

![Dashboard Home](./docs/images/ui-dashboard-home.png)
![Proposal Detail](./docs/images/ui-proposal-detail.png)
![Integrated Decision Review](./docs/images/ui-decision-review.png)
![Outcome Analysis](./docs/images/ui-outcome-analysis.png)

## Demo Workflow

1. Seed demo data:

```bash
.venv/bin/bot demo seed
```

2. Inspect operator state from the CLI:

```bash
.venv/bin/bot alerts list --state open
.venv/bin/bot proposals list --scope approved
.venv/bin/bot intents list --scope terminal
.venv/bin/bot markets live demo_rates_2026
```

3. Start the UI:

```bash
.venv/bin/bot ui serve
```

Module entrypoint works as well:

```bash
.venv/bin/python -m bot.cli.app demo seed
.venv/bin/python -m bot.cli.app proposals list --scope approved
.venv/bin/python -m bot.cli.app ui serve --host 127.0.0.1 --port 8080
```

4. In the UI:
- check the dashboard summary cards
- open an approved proposal
- inspect live market data for its market
- open its integrated decision review
- inspect the latest execution evaluation
- open saved views
- open export pages from decision review or analysis pages

## Telegram Operator Inbox

Start the read-only Telegram operator inbox:

```bash
.venv/bin/bot telegram serve
```

Required environment:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

Supported commands:
- `/start`
- `/help`
- `/status`
- `/diagnostics`
- `/scan`
- `/proposals`
- `/proposal <id>`
- `/approve <id>`
- `/reject <id>`
- `/cancel <id>`
- `/analysis <id>`
- `/alerts`

Phase 2 adds safe proposal lifecycle actions:
- allowlisted operators may approve, reject, cancel, and request additional analysis for proposals
- proposal actions reuse the existing lifecycle and decision-review services
- inline buttons are included on draft proposal notifications and proposal detail responses

Telegram still remains execution-safe:
- no intent creation
- no execution submission
- no runtime/config mutation
- no order posting
- no live execution

## Live Market Data

Public market-data integration uses:
- Gamma API for market/event metadata
- CLOB REST endpoints for public `/book`, `/midpoint`, and `/price`
- public market WebSocket updates with reconnect/backoff and receive-timeout fail-closed handling
- cache-first market inspection with explicit refresh

Catalog entry points:
- CLI: `bot markets catalog --scope active|closed|all [--limit N]`
- CLI: `bot events catalog --scope active|closed|all [--limit N]`
- CLI: `bot markets scan [--min-edge N] [--min-liquidity N] [--limit N]`
- CLI: `bot markets draft-opportunities [--min-edge N] [--min-liquidity N] [--limit N]`
- UI: `/catalog/markets`
- UI: `/catalog/events`

Examples:
- `bot markets catalog --scope active`
- `bot markets catalog --scope closed`
- `bot markets catalog --scope all`
- `bot markets scan --min-edge 0.08 --limit 10`
- `bot markets draft-opportunities --min-edge 0.08 --limit 5`

`bot markets scan` is a read-only opportunity scan. It scans active markets, loads current cached-or-live market pricing, applies a deterministic scanner fair-value heuristic, computes `edge = fair_probability - market_price`, filters by absolute edge magnitude, and sorts the output by descending absolute edge then confidence.
`bot markets draft-opportunities` stays read-only with respect to execution: it runs the scanner, skips markets that already have an active proposal, and creates safe draft proposals through the existing proposal lifecycle only. It does not approve proposals, create intents, or change execution behavior.

Approval revalidation now fails closed if public market data is stale, malformed, or unavailable.
This integration does not enable live trading:
- no authenticated trading
- no order posting
- no user channel
- live execution remains disabled

## Diagnostics

Use the read-only Polymarket connectivity diagnostics command to verify operator setup:

```bash
.venv/bin/bot diagnostics polymarket
```

It checks:
- Gamma API reachability
- CLOB REST reachability
- public market WebSocket handshake smoke
- resolved SQLite database configuration and connectivity

Example output:

```text
Polymarket diagnostics

Gamma API .......... OK (reachable)
CLOB REST .......... OK (reachable)
WebSocket .......... FAIL (timeout)
Database ........... OK (sqlite ready)

Overall status ..... FAIL
```

## Testing

Run the test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Compile check:

```bash
.venv/bin/python -m py_compile $(find bot tests -name '*.py' | sort)
```
