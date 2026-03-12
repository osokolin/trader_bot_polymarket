# Architecture Guardrails

This file defines non-negotiable architecture rules for `trader_bot_polymarket`.

All agents must read this before proposing, implementing, reviewing, or committing changes.

## 1. Core layer boundaries

The dependency direction must remain:

UI / CLI
→ Services
→ Adapters / Repositories
→ External APIs / Database

### Allowed responsibilities

#### UI
- render pages
- route requests
- call services
- use presenter helpers
- never contain business logic

#### CLI
- parse arguments
- call services
- render output via presenter
- never contain business logic
- never call adapters directly

#### Services
- orchestrate workflows
- enforce business logic
- enforce safety checks
- compose adapters and repositories
- may call adapters and repositories
- must not directly embed UI/CLI formatting concerns

#### Adapters
- integrate external APIs
- normalize external responses
- raise structured adapter errors
- must not contain business policy logic
- must not access repositories directly

#### Repositories
- persistence only
- read/write domain data
- no business decision logic
- no external API access

#### Domain models / enums
- source of truth for statuses, lifecycle states, and typed records
- should not depend on UI, CLI, or persistence implementation details

---

## 2. Thin-surface rule

UI and CLI must stay thin.

That means:

- no direct external API calls from UI
- no direct external API calls from CLI
- no persistence logic in UI
- no persistence logic in CLI
- no policy or execution decisions in presenters

If logic feels reusable, it belongs in a service.

---

## 3. External API rule

All external API integration must live in adapters.

For Polymarket this means:
- Gamma API access only in `bot/adapters/polymarket/*`
- CLOB REST access only in `bot/adapters/polymarket/*`
- WebSocket access only in `bot/adapters/polymarket/*`

Services may orchestrate those adapters.
UI/CLI must not call them directly.

---

## 4. Persistence rule

All database access must go through repositories.

Services may call repositories.
UI, CLI, adapters, and presenters must not write SQL or access DB handles directly.

No “temporary shortcut” is allowed.

---

## 5. State machine rule

Statuses and lifecycle transitions must remain explicit.

Rules:
- represent workflow states with enums where practical
- do not invent ad-hoc string statuses in services or UI
- invalid transitions must fail explicitly
- terminal vs active states should be modeled clearly

No silent transition skipping.

---

## 6. Safety rule

The following are non-negotiable:

- `semi_auto` remains strict
- real live execution remains disabled unless explicitly approved
- no autonomous execution
- no authenticated trading paths unless explicitly approved
- no order posting unless explicitly approved
- all live market-data failures must fail closed

No agent may weaken these rules.

---

## 7. Fail-closed rule

For external data:
- stale data must fail closed
- malformed data must fail closed
- unavailable data must fail closed
- no fabricated fallback values
- no silent downgrade that hides risk

Readable errors are allowed.
Unsafe continuation is not allowed.

---

## 8. New-layer rule

Do not introduce a new architectural layer without explicit approval.

Examples of risky drift:
- adding a “manager” layer when a service is enough
- adding helper modules that become hidden business logic
- moving domain logic into presenters
- creating UI-only versions of business workflows

If a new layer is truly needed, the Architect agent must justify it explicitly.

---

## 9. Service creation rule

A new service is justified only if it:
- owns a coherent workflow
- reduces duplicated orchestration
- preserves boundaries
- improves readability

A new service is not justified just to move code around.

---

## 10. Presenter rule

Presenter code may:
- format text
- format HTML fragments
- format summaries
- map status to labels/help text

Presenter code must not:
- call adapters
- call repositories
- decide workflow transitions
- enforce policy
- compute business outcomes

---

## 11. Review rule

Any change must be flagged if it does one of the following:

- UI calls repository directly
- CLI calls adapter directly
- adapter calls repository directly
- repository contains business logic
- service contains presentation formatting
- presenter contains business policy
- raw strings replace domain enum lifecycle
- safety boundary is weakened

These are architecture violations, not style issues.

---

## 12. Allowed exceptions

Temporary exceptions are allowed only if:
1. they are explicitly documented,
2. they are approved by Architect review,
3. they are isolated,
4. they have a follow-up plan.

“Quick shortcut” is not a valid justification.

---

## 13. Agent enforcement

### Planner
Must avoid proposing milestones that violate these boundaries.

### Architect
Must block architecture drift.

### Implementer
Must implement within these rules.

### Reviewer
Must flag violations explicitly.

### Security
Must flag any safety-boundary weakening.

### Committer
Must refuse commits that bypass these guardrails.