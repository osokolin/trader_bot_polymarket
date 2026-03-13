# Architecture

This document describes the high-level architecture of the trading assistant.

The system is intentionally designed as a policy-first operator assistant.
Autonomous trading is explicitly out of scope.

---

# System Design Principles

## Policy First

All trade proposals pass through a composite policy engine before becoming actionable.

Policies evaluate:

- sizing
- risk limits
- liquidity conditions
- probability sanity checks

## Fail Closed

If required data is missing or stale:

proposal → rejected

## Manual Operator Approval

No proposal can be executed without explicit operator approval.

---

# Core Components

## Market Data Layer

Adapters fetch public data from Polymarket:

- order books
- midpoint prices
- market metadata
- events

These feeds power:

- snapshot cache
- signal evaluation
- opportunity scanning

---

## Proposal Engine

The proposal engine combines:

market snapshot
signal
probability estimate

to produce candidate trade proposals.

Pipeline:

market data
→ probability model
→ sizing
→ composite policy
→ proposal generation

---

## Policy Layer

Policies enforce safety constraints.

Examples:

- max position sizing
- liquidity checks
- probability sanity
- duplicate proposal prevention

Policies are evaluated through a composite policy system.

---

## Proposal Lifecycle

States:

draft
policy_passed
pending_manual_confirmation
approved
paper_execution
evaluation

Terminal states:

policy_rejected
cancelled
expired

Approval always triggers pre-trade revalidation.

---

## Decision Inbox

Operator decisions are stored in a persistent inbox.

Examples:

- proposal approval
- proposal rejection
- alert acknowledgement

---

## Telegram Interface

Telegram is the primary operator interface.

Routing:

TelegramRouter
    ↓
TelegramOperatorService
    ↓
DecisionInboxService

---

## Opportunity Scanner

Detects potential trading opportunities.

Modes:

Alert mode → creates alerts
Draft mode → creates draft proposals

Runs:

- manually via CLI
- periodically during Telegram runtime

---

## Storage

SQLite stores:

- proposals
- alerts
- inbox requests
- audit logs
- execution records

---

## Web Operator UI

Provides:

- diagnostics
- proposal browsing
- operational visibility

Security:

single user
session authentication
localhost-only access

Production access via SSH tunnel.

---

# Architecture Constraints

The system must never:

- execute trades autonomously
- bypass policy evaluation
- bypass proposal lifecycle
- create hidden execution paths

All automation must route through:

policy
proposal lifecycle
audit logging
