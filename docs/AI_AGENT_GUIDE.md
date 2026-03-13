# AI_AGENT_GUIDE.md

This document helps AI agents quickly understand how to interact with the repository.

It complements PROJECT_CONTEXT.md.

---

# First Steps

When starting work:

1. Read PROJECT_CONTEXT.md
2. Review docs/ARCHITECTURE.md
3. Understand the proposal lifecycle
4. Confirm safety constraints

Agents must assume the system is **semi-automatic**.

---

# Critical Safety Constraints

The system must never:

- execute trades automatically
- bypass policy evaluation
- bypass the proposal lifecycle

All trade actions require manual operator approval.

---

# Important Components

Key subsystems:

- proposal engine
- policy framework
- decision inbox
- opportunity scanner
- Telegram operator interface

Agents should modify these systems carefully and incrementally.

---

# Typical Tasks

AI agents are expected to assist with:

- improving scanner quality
- improving operator workflows
- adding diagnostics
- enhancing observability
- refactoring code safely
- improving documentation

Agents should avoid large architectural redesigns.

---

# Change Strategy

Preferred change pattern:

1. minimal code change
2. verify behavior
3. add tests
4. update documentation

---

# Common Pitfalls

Agents must avoid:

- bypassing lifecycle logic
- introducing parallel execution paths
- embedding business logic in UI layers
- removing safety checks

---

# When Unsure

If the impact of a change is unclear:

- review existing services
- search for similar implementations
- choose the least disruptive solution
