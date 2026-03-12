# Merge / Commit Gates

A change is green only if all gates below pass.

## Gate 1 — Scope
- The change matches the approved milestone.
- No unrelated refactors unless explicitly justified.
- Scope stays reviewable.

## Gate 2 — Safety
- `semi_auto` still strict.
- Real live execution still disabled.
- No autonomous execution.
- No authenticated trading added unless explicitly approved.
- No order submission enabled.

## Gate 3 — Architecture
- UI does not access repositories directly.
- UI does not access adapters directly.
- CLI does not duplicate service logic.
- Adapters contain external API integration.
- Services orchestrate logic.
- Repositories handle persistence only.
- No unapproved new architectural layers.

## Gate 4 — Testing

Preferred:

### Fast verification
```bash
scripts/verify-fast.sh