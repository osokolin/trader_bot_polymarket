# Polymarket AI Bot — Starter Pack for Codex

## Goal
Build an MVP of a **semi-automatic Polymarket trading assistant** focused on event-driven markets.

The bot must:
- monitor selected Polymarket markets,
- ingest market data,
- analyze market rules and external signals,
- estimate fair probability,
- detect edge,
- validate every proposed trade through a strict policy engine,
- generate trade proposals for manual approval,
- never place a live order without explicit confirmation in `semi_auto` mode.

## Core product principles
1. **Policy-first architecture**: strategy can suggest trades, but policy decides whether they are allowed.
2. **Configuration over hardcoding**: trading rules, thresholds, sources, and mode selection must live in config files.
3. **Explainability**: every trade proposal and every rejection must include human-readable reasons.
4. **Safety first**: live execution is disabled by default.
5. **Deterministic guardrails** around any AI-assisted logic.
6. **Semi-auto by default**: the system prepares trades, but a human approves them.

---

## Scope for MVP

### In scope
- Polymarket market discovery and metadata ingestion
- Order book / price ingestion
- Local storage of markets, signals, proposals, and positions
- Policy engine
- YAML config with comments
- Config reference markdown
- Semi-auto workflow
- CLI interface for proposals and approvals
- Paper mode
- Basic live execution interface abstraction
- Rule parsing abstraction
- News/signal abstraction
- Audit logs

### Out of scope for MVP
- Full autonomous live trading
- Aggressive market making
- HFT / ultra-low-latency logic
- Sports or live-event markets
- Complex cross-exchange arbitrage
- Portfolio optimization beyond simple rule-based sizing
- Production-grade UI dashboard

---

## Operating modes
- `paper`: simulate entries/exits, no real orders
- `manual_only`: analytics only, no executable proposals
- `semi_auto`: generate executable proposals but require approval before sending any order
- `live_small`: reserved for future use
- `live_full`: reserved for future use

For MVP, fully support:
- `paper`
- `manual_only`
- `semi_auto`

`semi_auto` is the default mode.

---

## High-level architecture

```text
market data -> strategy -> scoring -> policy engine -> proposal -> manual approval -> execution -> monitoring -> exit proposal
```

### Main subsystems
1. `market_data`
2. `rules_parser`
3. `signal_engine`
4. `probability_engine`
5. `policy_engine`
6. `proposal_engine`
7. `execution_engine`
8. `position_monitor`
9. `storage`
10. `cli`

---

## Suggested tech stack
- Python 3.12+
- Poetry or uv for dependency management
- Typer for CLI
- Pydantic for typed settings and domain models
- SQLAlchemy + SQLite for MVP persistence
- httpx for HTTP clients
- websockets for stream handling
- PyYAML or ruamel.yaml for config loading
- Rich for terminal output
- pytest for tests

Optional but useful:
- structlog for logs
- alembic for migrations

---

## Suggested project structure

```text
polymarket-bot/
  README.md
  pyproject.toml
  .env.example
  .gitignore

  config/
    base.yaml
    conservative.yaml
    balanced.yaml
    aggressive.yaml
    sources.yaml
    whitelist.yaml
    blacklist.yaml

  docs/
    CONFIG_REFERENCE.md
    SEMI_AUTO_WORKFLOW.md
    ARCHITECTURE.md

  bot/
    __init__.py
    main.py

    cli/
      __init__.py
      app.py

    config/
      __init__.py
      loader.py
      models.py

    domain/
      __init__.py
      enums.py
      models.py
      decisions.py

    storage/
      __init__.py
      db.py
      models.py
      repositories.py

    services/
      __init__.py
      market_data.py
      rules_parser.py
      signal_engine.py
      probability_engine.py
      proposal_engine.py
      execution_engine.py
      position_monitor.py
      policy_engine.py
      sizing.py
      audit_log.py

    policies/
      __init__.py
      base.py
      market_policy.py
      risk_policy.py
      execution_policy.py
      ai_policy.py
      composite_policy.py

    adapters/
      __init__.py
      polymarket/
        __init__.py
        client.py
        models.py
        market_stream.py
        trading.py

    prompts/
      rules_parser.md
      news_analysis.md
      signal_summary.md

    utils/
      __init__.py
      time.py
      math.py
      ids.py

  tests/
    test_config_loader.py
    test_policy_engine.py
    test_sizing.py
    test_proposal_flow.py
    test_semi_auto_approval.py
```

---

## Required domain concepts

Codex should define clear typed domain models for:
- `Market`
- `OrderBookSnapshot`
- `Signal`
- `ProbabilityEstimate`
- `PolicyDecision`
- `TradeProposal`
- `ApprovalDecision`
- `Position`
- `ExitProposal`
- `AuditEvent`

### Required enums
- `BotMode`
- `ProposalStatus`
- `PositionStatus`
- `TradeAction`
- `PolicyRejectionReason`
- `SourceType`

---

## Policy engine requirements

Every trade must pass through a policy engine.

### Policy engine responsibilities
- validate market category
- validate whitelist / blacklist
- validate liquidity and spread
- validate time to resolution
- validate rules clarity
- validate model confidence
- validate trusted source requirements
- validate bankroll exposure limits
- validate unresolved exposure limits
- validate daily/weekly risk limits
- validate order type restrictions
- validate stale data constraints

### Required output format
The policy engine must never return just `True/False`.
It must return a structured decision such as:

```json
{
  "allowed": false,
  "reasons": [
    "market_not_whitelisted",
    "spread_too_wide",
    "confidence_below_threshold"
  ],
  "details": {
    "spread_pct": 0.052,
    "max_allowed_spread_pct": 0.03
  }
}
```

### Policy layering
Implement these layers:
- `market_policy`
- `risk_policy`
- `execution_policy`
- `ai_policy`
- `composite_policy`

---

## Semi-auto mode definition

In `semi_auto` mode the bot:
- may discover markets,
- may score markets,
- may compute fair probability,
- may compute edge,
- may run policy checks,
- may prepare executable trade proposals,
- may recommend position size and limit price,
- may monitor live positions,
- may prepare exit proposals,
- **must not place a live order until explicit user approval is received**.

### Semi-auto workflow
1. Detect market
2. Ingest latest metadata and order book
3. Parse rules / context
4. Generate signal
5. Estimate fair probability
6. Compute edge
7. Run composite policy
8. If rejected: log rejection with reasons
9. If approved: create `TradeProposal` with status `pending_manual_confirmation`
10. Display proposal in CLI
11. Accept one of these actions:
   - `approve`
   - `approve <size>`
   - `edit size <value>`
   - `edit price <value>`
   - `reject`
   - `snooze <minutes>`
12. Re-run pre-trade checks immediately before submission
13. If still valid, submit order
14. Track fills
15. Monitor exit conditions
16. Generate exit proposal and require approval again in `semi_auto`

### Important semi-auto constraints
- approval expires after a short TTL, e.g. 5 minutes
- old proposals cannot be executed without refresh
- pre-trade checks must run again right before submission
- if market data changed materially, the proposal must be recalculated
- all actions must be audit logged

---

## CLI requirements

Build a CLI with Typer.

### Minimum commands
- `bot run`
- `bot scan`
- `bot proposals list`
- `bot proposals show <id>`
- `bot proposals approve <id>`
- `bot proposals reject <id>`
- `bot proposals edit-size <id> <amount>`
- `bot proposals edit-price <id> <price>`
- `bot positions list`
- `bot positions close <id>`
- `bot config validate`
- `bot safety pause`
- `bot safety resume`
- `bot safety kill-switch`

### CLI display expectations
For any proposal, show:
- market title
- market id
- action
- market price
- fair probability
- edge
- confidence
- recommended size
- max allowed size
- suggested limit price
- thesis bullets
- risks bullets
- policy decision
- TTL / expiration timestamp

---

## Config requirements

Config must live in YAML files and include comments directly in the files.

### Required config files
- `config/base.yaml`
- `config/conservative.yaml`
- `config/balanced.yaml`
- `config/aggressive.yaml`
- `config/sources.yaml`
- `config/whitelist.yaml`
- `config/blacklist.yaml`

### Required docs file
- `docs/CONFIG_REFERENCE.md`

### Config loading rules
- base config loaded first
- profile config merged over base config
- whitelist / blacklist loaded separately
- sources loaded separately
- environment variables may override secrets and runtime options

### Required top-level config sections
- `mode`
- `bankroll`
- `position_limits`
- `market_filters`
- `entry_rules`
- `exit_rules`
- `ai_policy`
- `approvals`
- `safety`

---

## Example `config/base.yaml`

```yaml
# Режим работы бота.
# Возможные значения:
# - paper: только симуляция, без реальных ордеров
# - manual_only: бот ничего не исполняет, только показывает аналитику
# - semi_auto: бот готовит сделку, но ждет подтверждение
# - live_small: бот может исполнять маленькие реальные сделки
# - live_full: бот может исполнять сделки в полном разрешенном объеме
mode: semi_auto

bankroll:
  # Общий размер капитала, от которого считаются лимиты риска.
  total_usd: 1000

  # Доля капитала, которую бот никогда не использует в новых сделках.
  # Это защитный резерв на случай волатильности, ошибок или новых возможностей.
  reserve_ratio: 0.20

  # Максимально допустимый убыток за один день.
  # При достижении этого значения бот должен остановить новые входы.
  max_daily_loss_usd: 40

  # Максимально допустимый убыток за неделю.
  # При достижении этого значения live-торговля ставится на паузу.
  max_weekly_loss_usd: 120

position_limits:
  # Максимальная доля капитала в одной позиции.
  # Например 0.07 = не более 7% банка на один рынок.
  max_position_pct: 0.07

  # Максимальная суммарная доля капитала на одну тему.
  # Например если несколько рынков связаны с одним и тем же событием.
  max_theme_exposure_pct: 0.15

  # Максимальное количество одновременно открытых позиций.
  max_open_positions: 4

  # Максимальная доля капитала в рынках, которые еще не завершились.
  # Нужна, чтобы не "заморозить" весь банк в долгих ставках.
  max_unresolved_exposure_pct: 0.35

market_filters:
  # Категории рынков, в которых бот вообще может искать сделки.
  allowed_categories:
    - politics
    - crypto
    - legislation

  # Категории, которые бот должен всегда игнорировать.
  blocked_categories:
    - sports
    - entertainment_live

  # Минимальная ликвидность рынка в долларах.
  # Если ликвидность ниже, бот рынок пропускает из-за повышенного риска плохого исполнения.
  min_liquidity_usd: 3000

  # Максимально допустимый спред между лучшей ценой покупки и продажи.
  # Если спред выше, вход считается слишком дорогим.
  max_spread_pct: 0.03

  # Минимальное время до резолва рынка в часах.
  # Бот не входит слишком близко к дедлайну.
  min_time_to_resolution_hours: 24

  # Требование, чтобы у рынка были понятные и однозначные resolution rules.
  require_clear_rules: true

  # Требование, чтобы рынок поддерживал order book и можно было аккуратно ставить лимитки.
  require_orderbook: true

entry_rules:
  # Минимальный edge для входа.
  # Например 0.05 означает, что ожидаемое преимущество должно быть не менее 5%.
  min_edge_pct: 0.05

  # Минимальная уверенность модели в своей оценке вероятности.
  # Если confidence ниже порога, сигнал не используется.
  min_confidence: 0.70

  # Минимальное число независимых подтверждений сигнала.
  # Например: rules parser + news analyzer + probability model.
  min_model_agreement: 2

  # Требование, чтобы сигнал был основан хотя бы на одном доверенном источнике.
  require_trusted_source: true

  # Максимально допустимое движение цены за последние 15 минут.
  # Если цена уже резко улетела, бот не должен запрыгивать поздно.
  max_price_jump_15m_pct: 0.08

  # Разрешенный тип ордеров.
  # Для старта безопаснее использовать только limit_only.
  order_type: limit_only

exit_rules:
  # За сколько часов до резолва бот должен принудительно закрыть позицию.
  # Нужен, если стратегия ориентирована на торговлю до резолва, а не на удержание до конца.
  close_before_resolution_hours: 12

  # Порог "схлопывания edge".
  # Если рыночная цена приблизилась к справедливой оценке, позиция закрывается.
  take_profit_edge_collapse_pct: 0.02

  # Максимально допустимое ухудшение оценки вероятности модели после входа.
  # Если модель пересчитала вероятность сильно против позиции, бот выходит.
  stop_loss_prob_shift_pct: 0.06

  # Максимальное время удержания позиции в часах.
  # Это time stop: даже если ничего не произошло, позиция не должна висеть слишком долго.
  max_holding_hours: 72

ai_policy:
  # Может ли AI напрямую отправлять ордера.
  # Для безопасного старта должно быть false.
  ai_can_place_orders: false

  # Может ли AI только оценивать сигнал и объяснять его.
  ai_can_only_score: true

  # Минимальная уверенность парсера правил рынка.
  # Если AI не уверен, как трактовать rules, рынок блокируется.
  min_rules_parser_confidence: 0.80

  # Минимальная оценка релевантности новости к конкретному рынку.
  min_news_relevance_score: 0.75

  # Разрешенные типы источников для принятия решений.
  allowed_source_types:
    - official
    - regulator
    - major_media

approvals:
  # Требуется ли ручное подтверждение сделки человеком.
  # Для semi_auto обычно true.
  manual_approval_required: true

  # Порог, выше которого сделка теоретически может быть автоисполнена.
  # В semi_auto обычно не используется, но можно оставить на будущее.
  auto_execute_if_score_above: 0.90

  # Глобальный запрет автоисполнения.
  # Пока true, бот никогда сам не отправит реальный ордер.
  auto_execute_disabled: true

  # Сколько минут действует подтверждение сделки после выдачи сигнала.
  proposal_ttl_minutes: 5

safety:
  # Главный аварийный выключатель.
  # Если false, бот не должен открывать новые позиции.
  kill_switch_enabled: true

  # Сколько подряд ошибок API допустимо до автоматической паузы.
  pause_on_api_errors: 3

  # После какого количества подряд убыточных сделок бот должен остановить live-входы.
  pause_on_consecutive_losses: 4

  # Ставить ли торговлю на паузу при рассинхроне состояния позиции.
  # Например, если локально бот считает, что позиции нет, а на бирже она есть.
  pause_on_unexpected_position_state: true
```

---

## Example `config/sources.yaml`

```yaml
official_sources:
  - sec.gov
  - congress.gov
  - senate.gov
  - house.gov
  - whitehouse.gov

regulator_sources:
  - cftc.gov
  - federalreserve.gov
  - treasury.gov

major_media_sources:
  - reuters.com
  - apnews.com
  - bloomberg.com
```

---

## Example `config/whitelist.yaml`

```yaml
allowed_market_ids: []
allowed_tags:
  - crypto
  - regulation
  - politics
```

---

## Example `config/blacklist.yaml`

```yaml
blocked_market_ids: []
blocked_patterns:
  - live
  - sports
  - celebrity
  - gossip
```

---

## Required docs: `docs/CONFIG_REFERENCE.md`

Codex should generate a human-readable reference for every config field, including:
- purpose
- type
- example
- effect of setting lower or higher values
- interactions with related settings

---

## Proposal model expectations

Each `TradeProposal` must include at least:
- proposal id
- market id
- market title
- action
- side
- market price
- fair probability
- edge
- confidence
- recommended size usd
- max allowed size usd
- suggested limit price
- thesis
- risks
- proposal status
- creation timestamp
- expiry timestamp
- policy decision

### Proposal status values
- `detected`
- `scored`
- `policy_rejected`
- `pending_manual_confirmation`
- `approved`
- `submitted`
- `partially_filled`
- `filled`
- `cancelled`
- `exit_pending_confirmation`
- `closed`
- `paused_by_safety`

---

## Position sizing requirements

For MVP, implement a conservative rule-based sizing engine.

### Sizing inputs
- bankroll total
- reserve ratio
- max position pct
- theme exposure
- current unresolved exposure
- confidence
- edge

### Sizing output
- recommended size usd
- max allowed size usd
- explanation of how size was derived

Suggested MVP behavior:
- start from `bankroll.total_usd * max_position_pct`
- reduce size if confidence is only slightly above threshold
- reduce size if theme exposure is elevated
- reduce size if liquidity is marginal
- never exceed unresolved exposure limits

---

## Storage requirements

Use SQLite for MVP.

Persist at minimum:
- markets
- order book snapshots or latest market state
- signals
- policy decisions
- trade proposals
- approvals / rejections
- positions
- audit events

---

## Audit logging requirements

Every meaningful action must be logged, including:
- market discovered
- signal generated
- proposal created
- proposal rejected by policy
- proposal approved manually
- proposal edited
- proposal expired
- order submitted
- order rejected
- order filled
- exit proposal created
- position closed
- safety pause triggered
- kill switch activated

---

## Testing requirements

Codex must include tests for:
- config loading and merging
- YAML validation
- policy rejection reasons
- sizing limits
- proposal TTL expiration
- semi-auto approval path
- re-check before submit
- kill switch behavior
- unresolved exposure enforcement

---

## Implementation milestones

### Milestone 1 — Project scaffold
- create project structure
- setup config loader
- define domain models
- setup CLI skeleton
- setup SQLite persistence

### Milestone 2 — Policy-first core
- implement config models
- implement policy layers
- implement sizing engine
- implement proposal engine
- implement audit log

### Milestone 3 — Semi-auto workflow
- implement proposal listing
- implement approve/reject/edit flows
- add TTL handling
- add pre-trade revalidation

### Milestone 4 — Polymarket adapters
- market metadata adapter
- order book adapter
- execution adapter abstraction

### Milestone 5 — Signal / probability stub
- implement placeholder signal engine
- implement rules parser abstraction
- implement explainable proposal output

### Milestone 6 — Tests and docs
- complete tests
- write README
- write ARCHITECTURE.md
- write CONFIG_REFERENCE.md
- write SEMI_AUTO_WORKFLOW.md

---

## Acceptance criteria

The MVP is acceptable only if all of the following are true:
1. Bot runs in `paper` and `semi_auto` modes.
2. Every proposal passes through a structured policy engine.
3. Every rejection contains explicit reasons.
4. Every live action in `semi_auto` requires manual approval.
5. Approval expires after configured TTL.
6. A pre-trade validation reruns before submission.
7. Config is readable, commented, and documented.
8. Kill switch blocks new proposals from turning into orders.
9. Basic automated tests pass.
10. README explains how to run the bot locally.

---

## Explicit non-negotiable rules for Codex

- Do not hardcode trading thresholds in business logic.
- Do not allow direct AI-triggered live orders.
- Do not implement sports/live-market trading in MVP.
- Do not use market orders in MVP; use limit orders only.
- Do not return boolean-only policy decisions.
- Do not skip audit logging.
- Do not couple strategy logic with execution permissions.
- Do not make config undocumented.

---

## Recommended first delivery from Codex

Codex should produce a first PR or first iteration containing:
- full project scaffold
- typed config models
- commented YAML files
- config merge loader
- policy engine skeleton
- domain models
- proposal model
- Typer CLI skeleton
- SQLite setup
- tests for config + policy + TTL
- README with run instructions

---

## Ready-to-use prompt for Codex

```text
Build an MVP Python project for a Polymarket AI-assisted trading bot with a strict policy-first architecture.

Primary goal:
Create a semi-automatic event-trading assistant that discovers markets, scores them, checks them through a policy engine, and creates trade proposals for manual approval. In semi_auto mode, the bot must never place a live order without explicit approval.

Requirements:
1. Use Python 3.12+
2. Use Typer for CLI
3. Use Pydantic for typed config and domain models
4. Use SQLite for persistence
5. Store trading rules in YAML config files with human-readable comments directly in the YAML
6. Generate docs/CONFIG_REFERENCE.md describing every config field
7. Implement policy layers: market_policy, risk_policy, execution_policy, ai_policy, composite_policy
8. Implement structured PolicyDecision objects with allowed/reasons/details
9. Implement TradeProposal objects with proposal TTL and pending_manual_confirmation status
10. Implement semi_auto workflow with approve/reject/edit commands and pre-trade revalidation
11. Implement limit-order-only behavior for MVP
12. Implement audit logging for all meaningful actions
13. Add tests for config loading, policy checks, sizing, TTL expiry, kill switch, and semi_auto approval flow
14. Create the project structure exactly or very close to the one in the provided specification
15. Keep live execution abstracted and safe by default
16. Default mode must be semi_auto
17. Do not implement full autonomous trading
18. Do not implement sports or live-event markets in MVP

Deliverables:
- runnable project scaffold
- README.md
- docs/ARCHITECTURE.md
- docs/CONFIG_REFERENCE.md
- docs/SEMI_AUTO_WORKFLOW.md
- config/base.yaml
- config/conservative.yaml
- config/balanced.yaml
- config/aggressive.yaml
- config/sources.yaml
- config/whitelist.yaml
- config/blacklist.yaml
- tests

Use clear naming, strong typing, and readable code. Optimize for safety, maintainability, and explainability rather than speed.
```

---

## Notes for future phases
Future work may include:
- richer probability models
- external news ingestion
- LLM-assisted rules parsing
- web dashboard
- Telegram or Discord approval interface
- cross-market consistency checks
- profile-based runtime switching
- production deployment

---

## Agentic Rules for Codex

Use these as implementation rules for autonomous work on this repository.

### Mission
You are implementing a safe, policy-first, semi-automatic Polymarket trading assistant. Optimize for correctness, explainability, maintainability, and operational safety. Do not optimize for maximum trading aggressiveness.

### Core agentic rules
1. Always preserve the separation between:
   - strategy logic,
   - policy validation,
   - execution.
2. Never allow business logic to bypass the policy engine.
3. Never hardcode thresholds that belong in config.
4. Never implement real auto-execution in `semi_auto` mode.
5. Never let AI-generated output directly create a live order without deterministic validation.
6. Always make rejection reasons explicit and structured.
7. Prefer small, composable modules over large multifunction files.
8. Prefer typed models over raw dictionaries.
9. Prefer safe defaults over permissive defaults.
10. Every important state change must be audit logged.
11. Any ambiguous rule interpretation must fail closed, not fail open.
12. Any stale or incomplete market data must block execution.
13. Limit-order-only in MVP.
14. Any approval must expire after configured TTL.
15. Any order submission must run a final pre-trade validation.
16. When unsure, preserve safety and explain the limitation in code comments or docs.

### Coding behavior rules
1. Use Python 3.12+ idioms, type hints, and clear names.
2. Keep functions focused and small.
3. Avoid hidden side effects.
4. Write docstrings for public classes and functions.
5. Add tests for any non-trivial policy, sizing, approval, or config behavior.
6. Prefer explicit enums and value objects instead of free-form strings when practical.
7. Use Pydantic models for validated boundaries.
8. Use repository/service abstractions instead of mixing persistence into domain logic.
9. Keep adapters isolated from core domain.
10. Write code so that a future Telegram or web UI can reuse the same proposal workflow.

### Safety rules
1. Default mode is `semi_auto`.
2. `approvals.auto_execute_disabled` must remain effective unless explicitly changed in config.
3. Kill switch must block new order submission.
4. Stale proposal execution must be rejected.
5. Orderbook freshness must be checked before submit.
6. If local position state conflicts with exchange state, pause execution and log it.
7. If policy evaluation cannot complete, reject the trade proposal.
8. If required config is missing or invalid, fail startup with a clear error.

### Delivery rules
1. Build the project in milestones.
2. First deliver a runnable scaffold before deeper integrations.
3. Keep documentation updated with implementation.
4. Do not silently skip requested components.
5. If a requested feature is deferred, mark it clearly as stubbed or not yet implemented.

---

## Agentic Skills for Codex

Use these as internal working patterns while implementing the project.

### Skill 1 — Scaffold skill
When starting work:
- create the project structure,
- add dependency management,
- create config directories,
- create docs directories,
- create test skeletons,
- ensure the CLI starts successfully even before full integrations are complete.

### Skill 2 — Config modeling skill
For every config section:
- define a typed Pydantic model,
- validate constraints,
- add sensible defaults where appropriate,
- keep comments in YAML,
- mirror fields in `CONFIG_REFERENCE.md`.

### Skill 3 — Policy composition skill
When implementing policy logic:
- split checks into dedicated policy classes,
- return structured `PolicyDecision` objects,
- preserve rejection reasons,
- aggregate decisions in `composite_policy`,
- include human-readable details for debugging.

### Skill 4 — Proposal workflow skill
When implementing proposals:
- separate detection from approval,
- include TTL on all executable proposals,
- support approve/reject/edit flows,
- require revalidation before submit,
- log every proposal lifecycle transition.

### Skill 5 — Safe execution skill
When implementing execution code:
- keep exchange adapter behind an interface,
- support paper mode first,
- keep live execution minimal and guarded,
- reject market orders,
- verify freshness and limits immediately before sending.

### Skill 6 — Sizing skill
When implementing sizing:
- start from config maximums,
- reduce size based on confidence, liquidity, exposure, and risk state,
- always provide an explanation string,
- never exceed hard risk limits.

### Skill 7 — Storage skill
When implementing persistence:
- keep schema simple for MVP,
- store proposals, decisions, approvals, positions, and audit events,
- prefer clean repository methods,
- make it easy to replace SQLite later.

### Skill 8 — CLI skill
When implementing CLI flows:
- optimize for clear terminal interaction,
- display proposal rationale and risk clearly,
- make approval commands simple,
- ensure errors are actionable,
- keep command naming stable.

### Skill 9 — Testing skill
When adding tests:
- prioritize config loading,
- policy enforcement,
- TTL expiry,
- approval flow,
- kill switch,
- sizing limits,
- pre-trade validation.
Use fixtures and deterministic test data.

### Skill 10 — Documentation skill
When shipping features:
- update README,
- update architecture docs,
- update config reference,
- keep docs aligned with actual code behavior,
- document stubs and limitations honestly.

---

## How to hand this starter pack to Codex

Recommended approach:
1. Put this specification into the repository as a real file, for example:
   - `docs/CODEX_IMPLEMENTATION_BRIEF.md`
2. Ask Codex to read that file first before making changes.
3. In the task prompt, point Codex to the file and define the first milestone only.

### Best format
Prefer a real file in the repo over pasting everything into one short prompt.

Best option:
- create `docs/CODEX_IMPLEMENTATION_BRIEF.md`
- paste the full starter pack into that file
- then prompt Codex with a short instruction like:

```text
Read docs/CODEX_IMPLEMENTATION_BRIEF.md and implement Milestone 1 and Milestone 2 only.
Do not skip tests or docs.
Keep the architecture policy-first and semi_auto by default.
```

### Why this is better
- the brief stays versioned in the repo,
- Codex can refer back to it during implementation,
- you can refine it over time,
- it is easier to review diffs against a stable spec.

### Should it be one file?
Yes, for the starter pack, one main file is best.

Recommended structure:
- `docs/CODEX_IMPLEMENTATION_BRIEF.md` — full master spec
- optional later split into:
  - `docs/ARCHITECTURE.md`
  - `docs/CONFIG_REFERENCE.md`
  - `docs/SEMI_AUTO_WORKFLOW.md`

For the first handoff, one master brief is the cleanest option.

### What to include in the Codex prompt itself
Keep the prompt short and directive. Example:

```text
Read docs/CODEX_IMPLEMENTATION_BRIEF.md before doing anything else.
Implement the project scaffold, config system, policy engine skeleton, CLI skeleton, SQLite persistence, and tests for config/policy/TTL.
Do not implement autonomous live trading.
Ask no clarifying questions unless absolutely blocked; make reasonable safe assumptions and document them.
```

### What not to do
- do not rely only on a huge chat prompt with no file in the repo,
- do not scatter the initial requirements across many unrelated files before the first run,
- do not ask Codex to build everything in one pass,
- do not leave safety rules implied rather than explicit.

