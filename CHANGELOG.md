# CHANGELOG

All notable changes to this project will be documented in this file.

---

# Unreleased

## Added

Operator workflow improvements:

- Telegram decision inbox
- sequential review queue
- /review
- /review-next
- /skip

Market discovery:

- market catalog browsing
- opportunity scanning
- draft opportunity proposals

Background opportunity scanner:

- automatic scan integration in Telegram runtime
- configurable scan cadence

Operator UI:

- web authentication
- session management
- remember-browser tokens
- session revocation

Deployment improvements:

- GitHub Actions deployment
- SSH-based update workflow
- systemd services

---

# v1.0.0

Initial public release.

## Features

Core architecture:

- policy-first trading assistant
- semi-auto operator workflow
- strict safety boundaries

Proposal system:

- proposal generation
- composite policy engine
- lifecycle management
- approval revalidation

Market integration:

- Polymarket public API integration
- order book snapshots
- midpoint pricing
- WebSocket updates

Execution:

- paper execution
- outcome evaluation

Operator interfaces:

- CLI operator tooling
- Telegram bot interface

Infrastructure:

- SQLite persistence
- configuration system
- audit logging
