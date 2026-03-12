# Shared Project Context

Project: trader_bot_polymarket

## Product boundaries
- Paper-only semi-auto operator platform.
- Real live execution must remain disabled.
- No autonomous execution.
- Live market data may be integrated for inspection, research, and approval freshness only.

## Architecture expectations
- UI and CLI must stay thin.
- Business logic belongs in services.
- Persistence belongs in repositories.
- External APIs belong in adapters.
- Domain models and enums remain the source of truth for lifecycle and statuses.
- Do not introduce new architectural layers without explicit approval.

## Safety expectations
- `semi_auto` remains strict.
- All live market-data paths fail closed on stale or malformed data.
- No authenticated trading implementation.
- No order posting.
- No user websocket channel.
- No code path may silently weaken execution boundaries.

## Quality expectations
- Prefer the smallest safe step first.
- Prefer explicit state machines and typed models.
- Avoid architecture drift.
- Preserve demo seed workflow.
- Keep README and docs aligned with behavior.
- Keep test suite green.

## Unified developer entrypoint

All agents should prefer using:

scripts/dev verify
scripts/dev verify-fast
scripts/dev test
scripts/dev config
scripts/dev seed
scripts/dev scan
scripts/dev doctor

Do not call python or pip directly.