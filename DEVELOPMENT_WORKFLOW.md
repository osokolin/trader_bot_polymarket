# DEVELOPMENT_WORKFLOW.md

This document describes the recommended development workflow for the project.
It is designed to work well with both human developers and AI coding agents.

---

# Development Principles

The project follows several important principles:

- small milestones
- incremental development
- verify before commit
- documentation updated with behavior changes
- no architectural sprawl

All changes should preserve the safety boundaries defined in PROJECT_CONTEXT.md.

---

# Typical Development Cycle

1. Identify a milestone
2. Implement the smallest working change
3. Add or update tests
4. Run verification scripts
5. Update documentation if behavior changed
6. Commit with a clear message

Example workflow:

```
implement change
run verify-fast
fix issues
commit
push
```

---

# Milestone Structure

Milestones should be:

- small
- testable
- reversible

Examples:

- improve opportunity scanner heuristics
- add new Telegram command
- improve diagnostics output
- add observability metrics

Avoid large multi-system changes in a single milestone.

---

# Verification Commands

Fast verification:

```
scripts/dev verify-fast
```

Full verification:

```
scripts/dev verify
```

Fast verification includes:

- tests
- linting
- mypy checks
- compile checks

Full verification additionally includes:

- config validation
- demo seed

---

# Commit Guidelines

Commits should be clear and descriptive.

Examples:

```
feat: add opportunity scanner cooldown logic
fix: correct proposal TTL handling
docs: update architecture documentation
refactor: simplify proposal lifecycle transitions
```

Avoid vague commit messages.

---

# Testing Expectations

All behavior changes should include tests when possible.

Test types:

- unit tests
- service tests
- integration tests

Critical areas requiring tests:

- policy logic
- proposal lifecycle
- opportunity scanning
- Telegram routing

---

# Documentation Rules

Documentation must be updated when:

- new commands are added
- workflows change
- architecture boundaries change
- deployment steps change

Key documentation files:

- PROJECT_CONTEXT.md
- docs/ARCHITECTURE.md
- docs/RUNBOOK.md
- CHANGELOG.md

---

# Guidance for AI Agents

AI agents working on this repository should:

- read PROJECT_CONTEXT.md first
- preserve safety boundaries
- avoid introducing autonomous execution
- reuse existing services
- prefer small PR-sized changes
