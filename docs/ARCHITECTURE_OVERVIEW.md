# Architecture Overview

This project is a policy-first, semi-automatic operator assistant for Polymarket-style trading workflows.

## Core Principles

- Policy-first: strategy, probability, and research can suggest trades, but policy decides whether a proposal is allowed.
- Semi-auto by default: operator approval is required, live autonomous submission is disabled.
- Thin interfaces: CLI and UI are presentation layers over the same service layer.
- Persistence-first operator workflow: proposals, intents, alerts, reviews, audits, simulations, and analytics are stored in SQLite for later inspection.

## High-Level Flow

```text
market + probability + research
  -> proposal engine
  -> sizing
  -> composite policy
  -> proposal lifecycle
  -> manual approval/rejection/edit
  -> pre-trade revalidation
  -> approved proposal
  -> execution intent
  -> paper execution simulation
  -> decision review / execution evaluation / outcome analysis
  -> CLI and UI inspection
```

## Main Layers

### `bot/config`

- Loads YAML configuration.
- Applies profile overrides and environment overrides.
- Enforces invariants such as strict `semi_auto` defaults.

### `bot/domain`

- Shared enums and dataclasses.
- Defines proposals, intents, alerts, probability snapshots, decision reviews, simulations, and analysis snapshots.

### `bot/storage`

- Boots SQLite schema.
- Provides repositories for all persisted entities.
- Keeps state transitions queryable for operator workflows.

### `bot/policies`

- Contains policy layers such as market, risk, execution, and AI-policy checks.
- `CompositePolicy` merges reasons and namespaced detail payloads.

### `bot/services`

- Holds business logic.
- Main orchestration happens here:
  - proposal creation and lifecycle
  - approval revalidation
  - intent lifecycle
  - manual execution guard
  - paper execution simulation
  - decision review
  - execution evaluation
  - outcome analysis
  - alerts, watchlists, saved views, reporting, runtime safety

### `bot/adapters/polymarket`

- Wraps external market metadata and order-book access.
- Provides execution adapter abstractions.
- Real live execution remains disabled.

### `bot/cli`

- Operator CLI for inspection, lifecycle actions, analytics, exports, digests, demo seed, and UI launch.

### `bot/ui`

- Lightweight dashboard and detail pages.
- Reuses the same services as the CLI.
- Contains presentation only; does not own business rules.

### `bot/demo`

- Seeds a local operator-ready sandbox dataset for smoke testing and demos.

## Operator Workflow Model

### Proposal lifecycle

- A candidate proposal is created from market/probability context.
- Policy can reject immediately or allow `pending_manual_confirmation`.
- Operator can edit, reject, or approve.
- Approval triggers fresh revalidation.

### Intent lifecycle

- Only approved proposals can become order intents.
- At most one active intent per proposal unless explicitly superseded.
- `semi_auto` prevents live autonomous submission.

### Simulation path

- Prepared intents can be paper-simulated.
- Simulation records bid/ask-aware execution, latency, fill fragments, expiry, or cancellation.

### Review and learning path

- Probability snapshots and drift are persisted.
- Decision reviews combine proposal, drift, intent, and execution outcome.
- Execution evaluations compare intended vs simulated outcome.
- Outcome analysis aggregates patterns across markets and categories.

## Runtime Boundaries

- Default mode is `semi_auto`.
- Manual approval is required.
- Live execution remains disabled by config and guard policy.
- No autonomous execution is implemented.

## Interfaces

### CLI

Primary operator surface for:
- lifecycle actions
- inspections
- analytics
- exports
- digests
- demo seeding

### UI

Dashboard-oriented surface for:
- proposals
- intents
- alerts
- research snapshots
- integrated decision reviews
- outcome analysis
- saved views
- export views

## Where To Read Next

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [SEMI_AUTO_WORKFLOW.md](./SEMI_AUTO_WORKFLOW.md)
- [CONFIG_REFERENCE.md](./CONFIG_REFERENCE.md)
