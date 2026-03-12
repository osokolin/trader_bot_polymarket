# AGENTS.md

This repository uses a structured multi-agent workflow.

For detailed role definitions and workflows, see:

- `.agents/README.md`
- `.agents/shared-context.md`
- `.agents/architecture-guardrails.md`
- `.agents/gates.md`
- `.agents/planner.md`
- `.agents/architect.md`
- `.agents/implementer.md`
- `.agents/tester.md`
- `.agents/reviewer.md`
- `.agents/security.md`
- `.agents/committer.md`
- `.agents/workflows/next-step.md`
- `.agents/workflows/fix-pass.md`
- `.agents/workflows/release-pass.md`
- `.agents/prompts/`

All agents must treat `.agents/architecture-guardrails.md` as binding.

## Default agent flow

Planner → Architect → Implementer → Tester → Reviewer → Security → Committer

## Core project rules

1. Never work directly on `main`.
2. Keep `semi_auto` strict.
3. Keep real live execution disabled.
4. Do not implement autonomous execution.
5. Keep UI and CLI thin.
6. Keep business logic in services.
7. Keep external API logic in adapters.
8. Fail closed on stale, malformed, or unavailable external data.
9. Do not commit unless tests, review, and security gates pass.

## Unified developer entrypoint

Prefer using the unified project commands:

```bash
scripts/dev verify
scripts/dev verify-fast
scripts/dev test
scripts/dev config
scripts/dev seed
scripts/dev scan
scripts/dev doctor