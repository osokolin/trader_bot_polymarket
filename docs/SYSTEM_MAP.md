# SYSTEM_MAP.md

This document provides a practical map of the system for developers, reviewers, and AI agents.

It is intended to answer four questions quickly:

1. Where does data come from?
2. Which service owns which behavior?
3. How do operator actions flow through the system?
4. Where are the hard safety boundaries?

This file complements:

- `PROJECT_CONTEXT.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/AI_AGENT_GUIDE.md`

---

# 1. System Overview

The project is a policy-first, semi-automatic trading assistant for Polymarket-style workflows.

At a high level, the system combines:

- market metadata and prices
- internal proposal and policy logic
- operator-facing interfaces
- persistent storage
- audit logging

The core design goal is to help an operator discover, review, and act on trading opportunities without introducing autonomous execution.

---

# 2. Top-Level Map

The system can be understood as six major layers:

```text
External Data Sources
    ↓
Adapters
    ↓
Services
    ↓
Policies + Lifecycle Rules
    ↓
Storage
    ↓
Operator Interfaces
```

More concretely:

```text
Polymarket public APIs / WS
    ↓
bot/adapters/polymarket/*
    ↓
bot/services/*
    ↓
bot/policies/* + lifecycle services
    ↓
bot/storage/*
    ↓
CLI / Telegram / Web UI
```

---

# 3. Repository Map

Primary package layout:

```text
bot/
  adapters/
    polymarket/
  cli/
  config/
  domain/
  policies/
  services/
  storage/
  telegram/
```

Responsibility summary:

- `bot/adapters/`
  - external integrations
  - public Polymarket data access
  - order book / market metadata / pricing / websocket access

- `bot/cli/`
  - command-line entrypoints
  - operator utilities
  - maintenance and diagnostics commands

- `bot/config/`
  - configuration loading
  - typed settings
  - YAML parsing and validation

- `bot/domain/`
  - core enums
  - value objects
  - dataclasses used across layers

- `bot/policies/`
  - policy rules
  - composite policy evaluation
  - hard pre-execution safety checks

- `bot/services/`
  - application orchestration
  - proposal generation
  - lifecycle transitions
  - market snapshots
  - alerts
  - inbox and operator workflows

- `bot/storage/`
  - SQLite repositories
  - migrations
  - persistence model

- `bot/telegram/`
  - Telegram command routing
  - action parsing
  - response formatting

---

# 4. External Data Flow

The system currently depends on public Polymarket-facing data sources.

Main external inputs include:

- market metadata
- event metadata
- public order books
- midpoint / price data
- public websocket updates

Data path:

```text
Polymarket API / CLOB / WS
    ↓
adapter layer
    ↓
market snapshot services
    ↓
proposal generation / scanners / diagnostics
```

Important boundary:

- external data is read-only
- live authenticated trading is not part of the current architecture

---

# 5. Core Runtime Flows

## 5.1 Proposal Flow

This is the main decision-support flow.

```text
market snapshot
+ signal
+ probability estimate
        ↓
sizing logic
        ↓
composite policy evaluation
        ↓
proposal creation
        ↓
pending_manual_confirmation
        ↓
manual operator decision
        ↓
paper execution / simulation
        ↓
evaluation / analysis
```

Key ownership:

- proposal creation: service layer
- eligibility checks: policy layer
- state transitions: lifecycle services
- persistence: storage layer
- final operator decision: Telegram / CLI / UI interfaces

## 5.2 Alert Flow

This is the read-only discovery flow.

```text
scanner input
    ↓
opportunity detection
    ↓
alert creation
    ↓
dedupe
    ↓
persistence
    ↓
operator delivery
```

The alert flow must not create hidden execution behavior.

## 5.3 Draft Opportunity Flow

This is a safe bridge between discovery and manual review.

```text
scanner input
    ↓
opportunity detection
    ↓
draft proposal creation
    ↓
normal lifecycle + manual approval path
```

Important constraint:

- draft generation is allowed
- autonomous approval or execution is not allowed

---

# 6. Service Map

The service layer is the main orchestration layer.

It should remain the place where business workflows are coordinated.

Representative service responsibilities include:

## Proposal Services

Own:

- proposal generation
- proposal persistence
- proposal state transitions
- approval-time revalidation
- cancellation / expiry handling

These services should be reused instead of duplicating proposal logic in interface layers.

## Market Snapshot Services

Own:

- pulling and normalizing market data
- caching snapshots
- providing consistent data for proposal and scanner workflows

## Alert Services

Own:

- alert creation
- dedupe
- operator-facing alert delivery path
- opportunity scan orchestration

## Decision Inbox Services

Own:

- persistent review requests
- queue semantics
- request acknowledgement / skip behavior
- review ordering

## Telegram Operator Services

Own:

- bridging Telegram commands to application services
- safe execution of operator actions
- formatting and response coordination

Important design rule:

Telegram should call services.
Telegram should not become the place where business rules live.

---

# 7. Policy Map

Policies are a hard safety boundary.

They should remain explicit, testable, and independent from interface-specific logic.

Typical policy areas include:

- sizing limits
- liquidity requirements
- price sanity checks
- duplicate or conflicting proposal prevention
- stale-data rejection

Composite policy behavior:

```text
proposal candidate
    ↓
policy 1
policy 2
policy 3
...
    ↓
combined decision
```

Critical rule:

No proposal should bypass policy evaluation.

---

# 8. Proposal Lifecycle Map

The lifecycle is the main safety envelope around proposal handling.

Typical progression:

```text
draft
  ↓
policy_passed
  ↓
pending_manual_confirmation
  ↓
approved
  ↓
paper_execution
  ↓
evaluation
```

Alternative terminal or side paths:

```text
policy_rejected
cancelled
expired
```

Special rule:

Approval triggers immediate pre-trade revalidation.

That means:

```text
operator approves
    ↓
revalidation runs
    ↓
if OK → continue
if failed → policy_rejected
```

This is an intentional fail-closed design.

---

# 9. Storage Map

Persistence uses SQLite.

Storage responsibilities include:

- proposals
- alerts
- inbox requests
- audit events
- execution records
- cached or derived operational state where applicable

The storage layer should remain:

- simple
- explicit
- repository-based
- migration-backed

Design preference:

- business logic in services
- persistence logic in repositories
- not the other way around

---

# 10. Operator Interface Map

The project currently has three main operator-facing surfaces.

## 10.1 CLI

Used for:

- diagnostics
- manual scans
- operational commands
- maintenance workflows
- local development workflows

CLI should stay thin and call services.

## 10.2 Telegram

Telegram is the primary operator interaction surface.

Typical responsibilities:

- show status
- show diagnostics
- present proposals
- expose review queue
- allow safe proposal actions
- trigger scans

Representative command groups:

```text
/status
/diagnostics

/inbox
/review
/review-next
/skip

/proposals
/proposal
/approve
/reject
/cancel

/scan-opportunities
/alerts
```

Telegram routing pattern:

```text
TelegramRouter
    ↓
TelegramOperatorService
    ↓
domain services
    ↓
storage
```

## 10.3 Web UI

The web UI is a local authenticated operator dashboard.

Used for:

- proposal browsing
- diagnostics
- status visibility
- operational review

Security model:

- single-user authentication
- server-side sessions
- HttpOnly cookies
- localhost binding in production
- SSH tunnel access pattern

UI should remain a thin layer over service-owned behavior.

---

# 11. Background Scanner Map

A background opportunity scan can run when the Telegram runtime is active.

Flow:

```text
bot telegram serve
    ↓
periodic trigger
    ↓
MarketOpportunityAlertService.scan(...)
    ↓
normal alert pipeline
```

Cadence source:

- `market_opportunity_alerts.poll_interval_seconds`

Important architectural note:

- this is not a separate scheduler subsystem
- it is a small runtime trigger over existing scan logic
- delivery still goes through normal persistence / dedupe / Telegram alert paths

This is a good pattern to preserve in future work: reuse existing service flows instead of creating parallel infrastructure.

---

# 12. Web Auth and Operational Security Map

The authenticated web UI introduces a small security subsystem.

Current model:

- single-user operator auth
- password set out-of-band
- session-based authentication
- remember-browser tokens
- active session/token revocation

Operationally important points:

- UI is intended for localhost-only serving in production
- remote access is via SSH tunnel
- secrets and runtime config should remain outside the repo

---

# 13. Deployment Map

Production deployment path:

```text
push to main
    ↓
GitHub Actions
    ↓
SSH to server
    ↓
~/bin/trader-bot-update
    ↓
systemd user services restarted / refreshed
```

Operational runtime model:

- services run under a dedicated user
- project-local `.venv`
- config outside repo
- user-level systemd services for Telegram and UI

Representative services:

```text
trader-bot-telegram.service
trader-bot-ui.service
```

---

# 14. Test and Verification Map

Expected verification layers:

- unit tests for domain and policies
- service tests for workflows and transitions
- interface tests where routing behavior matters
- regression tests for safety-sensitive paths

Important verification targets:

- composite policy decisions
- lifecycle transitions
- approval-time revalidation
- scanner dedupe behavior
- Telegram review queue behavior
- stale-data fail-closed behavior

Canonical commands:

```text
scripts/dev verify-fast
scripts/dev verify
```

---

# 15. Hard Safety Boundaries

These are the boundaries that future work must preserve.

## Never Introduce

- autonomous trade execution
- hidden execution paths
- approval bypasses
- policy bypasses
- interface-owned business logic that silently changes lifecycle behavior

## Always Preserve

- manual operator approval
- explicit lifecycle transitions
- audit logging
- fail-closed checks on bad or stale data
- service-layer orchestration
- documentation updates when behavior changes

---

# 16. Common Change Patterns

Preferred patterns for safe evolution of the codebase:

## Good Pattern: Extend Existing Service

```text
new operator capability
    ↓
add method to existing service
    ↓
reuse lifecycle/policy/storage flow
    ↓
expose through CLI/Telegram/UI
```

## Bad Pattern: Add Interface-Specific Logic

```text
new Telegram command
    ↓
embed business rules directly in Telegram handler
    ↓
bypass shared services
```

## Good Pattern: Reuse Existing Scan Pipeline

```text
new trigger
    ↓
call existing scan service
    ↓
reuse dedupe / persistence / alert delivery
```

## Bad Pattern: Create Parallel Scheduler Stack

```text
new background need
    ↓
new scheduler subsystem
    ↓
duplicate scan logic
    ↓
diverging behavior
```

---

# 17. Guidance for Reviewers and AI Agents

When reviewing or modifying the system, ask:

1. Which service should own this behavior?
2. Does this reuse the existing lifecycle?
3. Does it preserve policy-first safety?
4. Is this adding a parallel path that should not exist?
5. Which docs need to be updated?

Recommended startup reading order for a new contributor or agent:

1. `PROJECT_CONTEXT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/SYSTEM_MAP.md`
4. `DEVELOPMENT_WORKFLOW.md`
5. `docs/AI_AGENT_GUIDE.md`

---

# 18. Practical Summary

If you remember only one compact map, use this one:

```text
Public market data
    ↓
Adapters
    ↓
Snapshot / proposal / alert services
    ↓
Policies + lifecycle revalidation
    ↓
SQLite persistence + audit log
    ↓
CLI / Telegram / Web UI
    ↓
Manual operator decision
```

And the most important invariant is:

```text
discovery may be automated
execution may not be automated
```
