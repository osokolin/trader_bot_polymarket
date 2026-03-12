# Agent Roles

This project uses a structured multi-agent workflow.

## Roles
- Planner — chooses the smallest useful next step.
- Architect — protects architecture boundaries and prevents design drift.
- Implementer — makes code changes only within the approved scope.
- Tester — runs verification commands and reports exact results.
- Reviewer — performs code review for correctness, safety, and maintainability.
- Security — reviews safety boundaries, external API integrations, and execution constraints.
- Committer — creates a commit only when all gates are green.

## Core rules
1. Never work directly on `main`.
2. Work only in an approved non-main branch.
3. Keep `semi_auto` strict.
4. Keep real live execution disabled.
5. Do not implement autonomous execution.
6. Keep UI and CLI thin.
7. Keep business logic in services.
8. Keep external API logic in adapters.
9. Fail closed on stale, malformed, or unavailable external data.
10. Do not commit unless tests, review, and security gates pass.
11. Architecture guardrails are defined in: - `.agents/architecture-guardrails.md`

These rules are binding for all agents.

## Preferred verification scripts

Use scripts when available:

### Fast verification
```bash
scripts/verify-fast.sh