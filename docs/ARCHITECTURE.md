# Architecture

The current implementation covers the earlier proposal/execution milestones plus public Polymarket market-data integration, while keeping execution strictly semi-automatic.

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
- `bot/storage`: SQLite schema bootstrap and repositories, split by bounded storage area with `repositories.py` kept as a thin compatibility facade
- `bot/policies`: policy layers and composite policy
- `bot/services`: sizing, proposal generation, lifecycle transitions, audit logging, approval-time snapshot wiring, and cached live market-data retrieval
- `bot/adapters/polymarket`: Gamma metadata, public CLOB `/book` + `/midpoint` + `/price`, public market WebSocket, and execution abstractions
- `bot/cli`: CLI skeleton for scan/proposal/position/safety/config commands

## Current boundaries

- Proposal lifecycle is stored in SQLite and controlled through explicit service methods.
- Persistence exists for milestone-1 entities and audit/proposal records needed by the core.
- Public live market data is retrieved through adapter-level Gamma/CLOB clients and cached locally as market snapshots.
- Approve revalidation uses fresh public market metadata and public CLOB `/book` + `/midpoint` pricing when a snapshot provider is configured, while `/price` is stored as explicit reference-price metadata.
- Public market-data failures are fail-closed: stale, malformed, or unavailable market data blocks approval.
- Live execution remains disabled; no authenticated trading, order posting, or user channel support is present.

## Bootstrap / Composition Root

- Runtime dependency construction now lives in `bot/bootstrap.py`.
- `AppContainer` owns explicit construction of database, repositories, adapters, and services for the CLI/UI/Telegram runtime.
- `DiagnosticsBootstrap` provides a smaller read-only composition root for Polymarket diagnostics without creating the full application graph.
- `bot/cli/app.py` stays focused on argument parsing, command dispatch, and presenter output.
- Demo/static UI rendering reuses the same bootstrap layer instead of hand-building a second service graph.

## Decision Inbox Handlers

- `DecisionInboxService` owns inbox semantics: request retrieval, queue ordering, request bookkeeping, and action recording.
- Request-type-specific action logic is delegated to explicit handlers under `bot/services/inbox_handlers/`.
- Proposal transitions still flow through `ProposalLifecycleService`; Telegram remains a thin caller through `TelegramOperatorService`.
