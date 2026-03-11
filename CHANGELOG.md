# Changelog

## v1.0.0

Initial operator-ready release.

### Added

- Policy-first proposal engine with YAML configuration and typed settings.
- Composite policy evaluation with namespaced detail aggregation.
- Proposal lifecycle with manual approval, rejection, edit flows, TTL expiry, and audit logging.
- Polymarket market metadata and order-book adapters for approval-time revalidation.
- Persisted order intents with strict semi-auto execution boundary.
- Paper execution simulation with bid/ask-aware fills, latency, partial fills, expiry, and cancellation paths.
- Probability snapshot persistence, research summaries, drift comparison, and evidence modeling.
- Decision reviews, execution evaluations, and grouped outcome analysis snapshots.
- Operator watchlists, alerts, saved views, exports, digests, demo seed workflow, and runtime safety inspection.
- Lightweight operator dashboard UI for proposals, intents, alerts, research, decision reviews, analysis, and exports.
- Demo seeding and smoke-test coverage for local operator workflows.

### Defaults and safety

- `architecture: policy-first`
- `mode: semi_auto`
- live execution disabled
- no autonomous execution

### Verification

- unit and integration-style tests pass locally
- compile check passes locally
