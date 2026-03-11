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
- Polymarket metadata and order-book adapters
- persisted order intents and simulation-only execution pipeline
- paper execution, decision review, execution evaluation, outcome analysis
- CLI operator tooling
- lightweight operator dashboard UI

See [docs/ARCHITECTURE.md](/Users/osokolin/IdeaProjects/trader_bot_polymarket/docs/ARCHITECTURE.md), [docs/CONFIG_REFERENCE.md](/Users/osokolin/IdeaProjects/trader_bot_polymarket/docs/CONFIG_REFERENCE.md), and [docs/SEMI_AUTO_WORKFLOW.md](/Users/osokolin/IdeaProjects/trader_bot_polymarket/docs/SEMI_AUTO_WORKFLOW.md).

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
.venv/bin/python -m bot.cli.app config validate
```

Or, after editable install:

```bash
bot config validate
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
bot analysis outcomes --group-by market
bot portfolio summary
```

Seed local demo data for operator testing:

```bash
bot demo seed
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
bot ui serve --host 127.0.0.1 --port 8080
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
- integrated decision review pages
- outcome analysis
- saved views
- export pages for decision reviews, execution evaluations, and outcome analysis

## Demo Workflow

1. Seed demo data:

```bash
bot demo seed
```

2. Inspect operator state from the CLI:

```bash
bot alerts list --state open
bot proposals list --scope approved
bot intents list --scope terminal
```

3. Start the UI:

```bash
bot ui serve
```

If the `bot` script is not yet on your path, use:

```bash
.venv/bin/python -m bot.cli.app demo seed
.venv/bin/python -m bot.cli.app proposals list --scope approved
.venv/bin/python -m bot.cli.app ui serve
```

4. In the UI:
- check the dashboard summary cards
- open an approved proposal
- open its integrated decision review
- inspect the latest execution evaluation
- open saved views
- open export pages from decision review or analysis pages

## Testing

Run the test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Compile check:

```bash
.venv/bin/python -m py_compile $(find bot tests -name '*.py' | sort)
```
