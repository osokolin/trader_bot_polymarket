# Codex Planning Mode

Use this mode for every non-trivial milestone.

The purpose is to force a design/planning pass before implementation.

This reduces:
- architectural drift
- accidental coupling
- milestone scope creep
- unsafe or unclear changes

---

# When to use Planning Mode

Planning Mode should be used when a milestone:

- touches multiple layers
- changes routing, UI, Telegram, or services
- introduces a new service
- adds persistence or migrations
- changes alerting or operator workflow
- changes a user-visible workflow
- affects safety boundaries

For very small isolated fixes, direct implementation is acceptable.

---

# Phase 1 — Plan Only

Codex must first produce a plan without modifying code.

Required outputs:

1. Goal summary
2. Architecture impact
3. Proposed service / UI / storage changes
4. Files expected to change
5. Risks
6. Test plan
7. Acceptance criteria
8. Non-goals

Important:
No code changes in Phase 1.

---

# Phase 2 — Implementation

Only after the plan is reviewed/accepted:

Codex may:
- implement code
- update tests
- update docs
- generate PR description

---

# Plan Format

Codex should structure the plan like this.

## Milestone
<name>

## Goal
<what this milestone is for>

## Why now
<why this milestone is the right next step>

## Proposed architecture
<flow / ownership / service boundaries>

## Expected files to change
- ...
- ...

## Risks
- ...
- ...

## Test plan
- ...
- ...

## Acceptance criteria
- ...
- ...

## Non-goals
- ...
- ...

---

# Implementation Rule

Do not begin coding until the plan is reviewed or explicitly approved.

---

# Safety Rule

Planning must explicitly confirm that the milestone does not violate:

- semi_auto safety boundaries
- no automatic proposal creation
- no automatic approval/rejection
- no execution shortcuts
- no policy mutation from UI/Telegram

---

# PR Rule

After implementation, Codex must still generate the final PR description using:

docs/PR_GUIDELINES.md