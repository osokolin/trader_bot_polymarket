# Architecture

The current implementation covers Milestones 1, 2, 3, and 4 from the brief, while keeping execution strictly semi-automatic.

## Principles

- Policy-first: strategy outputs are advisory, policy determines whether a trade may proceed.
- Configuration-first: runtime rules live in YAML config files under `config/`.
- Semi-auto default: `mode: semi_auto` and `manual_approval_required: true` are enabled in base config.

## Flow

```text
market snapshot + signal + probability
  -> sizing
  -> composite policy
  -> proposal engine
  -> audit log
```

## Package layout

- `bot/config`: YAML parsing, config merge, typed config models
- `bot/domain`: enums and domain dataclasses used across services
- `bot/storage`: SQLite schema bootstrap and repositories
- `bot/policies`: policy layers and composite policy
- `bot/services`: sizing, proposal generation, lifecycle transitions, audit logging, and approval-time snapshot wiring
- `bot/adapters/polymarket`: market metadata, order book, and execution abstractions
- `bot/cli`: CLI skeleton for scan/proposal/position/safety/config commands

## Current boundaries

- Live Polymarket adapters are intentionally stubbed for later milestones.
- Proposal lifecycle is stored in SQLite and controlled through explicit service methods.
- Persistence exists for milestone-1 entities and audit/proposal records needed by the core.
- Approve revalidation can use fresh Polymarket market/order book data when a snapshot provider is configured.
- If no live snapshot provider is configured, approve revalidation falls back to the proposal limit price and stored probability inputs.
