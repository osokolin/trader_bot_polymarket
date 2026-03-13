# Semi-Auto Workflow

The repository keeps `semi_auto` as the default operating mode.

At the current milestone depth:

1. Market and signal inputs are converted into a candidate trade proposal.
2. The candidate passes through the composite policy engine.
3. Approved proposals are persisted with status `pending_manual_confirmation`.
4. Operators may edit size and limit price while the proposal is still pending.
5. Manual approval triggers immediate pre-trade revalidation.
6. Revalidation failures move the proposal to `policy_rejected`.
7. Manual rejection or TTL expiry moves the proposal to `cancelled`.
8. Every transition is written to the audit log and to proposal review records.
9. Operators can inspect active and terminal proposals/intents, plus review and audit history, through CLI list/show commands.
10. Runtime safety inspection exposes the current mode, profile, kill switch state, unresolved exposure, and whether the semi-auto execution boundary is still strict.
11. CLI list output now distinguishes total-status summaries for the full result set from returned-page summaries after pagination.
12. Operators may run explicit paper simulations for prepared intents and inspect simulated execution history, slippage, reference price, and fill timestamps.
13. Simulation analytics expose per-intent and overall dry-run summary statistics, plus latest simulated execution lookup.
14. Portfolio and session summaries aggregate proposal, intent, and simulated execution metrics, with optional time-window filters.
15. Operators can maintain watchlists for markets, proposals, and intents, and inspect persisted alerts with watchlist-only filtering.
16. Probability and research snapshots are persisted on proposal creation and approval revalidation, and can be inspected by proposal or market.
17. Probability compare views expose drift between the latest and previous snapshots for the same proposal or market.
18. Decision review snapshots compose the latest proposal, probability snapshot, probability drift, intent, and simulated execution outcome into operator-readable post-hoc feedback by proposal or market.
19. Probability snapshots now retain normalized evidence records, per-source weights, and source-type contribution breakdowns for operator research inspection.
20. Paper execution now simulates bid/ask-aware pricing, latency, partial-fill fragments, and terminal completion paths such as filled, expired, or cancelled.
21. Execution evaluation snapshots now compare intended execution terms against simulated outcomes and persist operator-facing verdicts by intent or proposal.
22. Meta-analysis snapshots now aggregate decision review, drift, and execution outcome patterns by market, category, source type, confidence band, and verdict type.
23. Alerts now support acknowledgement, dismissal, and resolution states, while saved CLI views can persist common listing and analysis filters.
24. Operator exports and digest commands can emit persisted decision reviews, execution evaluations, outcome analyses, and daily/session summaries.
25. A lightweight operator dashboard UI is available via `bot ui serve`, with thin presentation-only pages for proposals, intents, alerts, research snapshots, decision reviews, and grouped outcome analysis.
26. The dashboard home page now surfaces summary cards plus latest open alerts, active proposals/intents, recent decision reviews, recent outcome analysis snapshots, alert lifecycle actions, and saved-view entry points.
27. `bot demo seed` can populate a local operator-ready sandbox dataset, and UI export pages now expose persisted decision review, execution evaluation, and outcome analysis payloads through the reporting layer.
28. Public live market data can now be inspected through Gamma metadata, public CLOB `/book` + `/midpoint` + `/price` endpoints, cached market snapshots, and a public market WebSocket path with reconnect/backoff plus receive-timeout detection.
29. Operator catalog views now expose public Gamma market and event listings through `bot markets catalog --scope active|closed|all`, `bot events catalog --scope active|closed|all`, `/catalog/markets`, and `/catalog/events`, with browse-only web filters for compact category multi-select, search, min liquidity, orderbook-only, supported sort modes, tooltip help, page-based browsing, a saved default catalog view, and a read-only market detail page at `/catalog/markets/<slug>` that now surfaces persisted research/operator context plus related proposal history when it exists.
30. `bot markets scan` provides a read-only market opportunity scan over active markets, using cached-or-live market pricing plus a deterministic scanner fair-value heuristic, with filtering by absolute edge magnitude, liquidity, and result limit.
31. `bot alerts scan-opportunities` is the dedicated one-shot read-only market discovery alert pass over active markets. It uses explicit tracked categories/keywords, high-liquidity thresholds, resolving-soon thresholds, and conservative existing-context presence to create deduplicated open alerts through the normal alert workflow. Country-keyword sports noise is suppressed using a conservative sports-context blocklist.
32. Telegram operators can trigger the same read-only path with `/scan-opportunities [limit]`. The Telegram command reuses the existing opportunity alert service and applies a short in-memory cooldown to reduce accidental spam.
33. When `bot telegram serve` is running, the Telegram runtime also hosts a small in-memory background trigger for the same opportunity scan service. It respects `market_opportunity_alerts.poll_interval_seconds`, avoids overlapping runs, logs failures without crashing the runtime loop, and lets newly created alerts continue through the normal alert + Telegram delivery path.
34. `bot markets draft-opportunities` can convert scanner results into safe draft proposals through the existing proposal lifecycle, while deduping against active proposals for the same market and leaving approval, intent creation, and execution unchanged.
35. `bot telegram serve` exposes an allowlisted Telegram operator inbox with concise status/diagnostics/scanner/proposal/alert commands, notification polling for new draft proposals, new open alerts, and diagnostics failures, plus safe proposal actions for approve/reject/cancel/request-analysis through the existing lifecycle services.
36. A persisted Decision Inbox now tracks operator action requests for proposal review, alert notifications, and diagnostics issues; Telegram exposes those requests through `/inbox`, `/request <id>`, and request-scoped action cards that resolve through the decision inbox service before delegating to lifecycle or alert services.
37. Telegram review sessions can now use `/review` and `/review-next` to process open decision requests sequentially in created order, with request-safe actions and skip support that keep execution boundaries unchanged.


Execution adapters remain non-autonomous; approval currently stops at a verified `approved` state.
When a live order book is available, approval revalidation uses fresh public market metadata plus fresh CLOB `/book` and `/midpoint` pricing, and `current_price` currently uses the midpoint as a temporary execution-price proxy.
The separate CLOB `/price` value is treated as a reference-price field; if it is unavailable, the snapshot records that explicitly in pricing metadata instead of fabricating a substitute.
If live market data is stale, malformed, or unavailable, approval fails closed and the proposal stays pending until the operator retries with healthy data.
Live execution remains disabled; `semi_auto` still requires manual approval and blocks autonomous order submission.
Public market-data integration does not include authenticated trading, order posting, or the Polymarket user channel.
Telegram proposal actions remain lifecycle-bound and execution-safe: they may approve, reject, cancel, or request additional analysis for proposals, but they do not create intents, submit orders, simulate execution, or mutate runtime mode/configuration.
Telegram decision cards are now request-based: proposal, alert, and diagnostics actions are scoped to persisted `request_id` records, preserving server-side auditability and keeping Telegram as a thin operator surface.
Operator inspection paths are cache-first by default. The UI live-market page and `bot markets live <market_id>` prefer the latest cached snapshot and only refresh externally when the operator asks for it.
Paper execution uses a deterministic dry-run adapter and writes simulated execution details to review and audit trails.
Terminal simulated intents are not re-simulated; operators must create a new intent if they need another scenario run.
Alerting currently covers TTL-nearing proposals, stale approved proposals, superseded active intents, and newly recorded simulated executions.
Probability snapshots now retain normalized key factors, source counts, confidence components, and research context for operator review.
Drift reporting highlights deltas in fair probability, confidence, source count, confidence components, and factor additions/removals.
Decision review output summarizes whether confidence held or degraded, whether probability moved in favor or against the trade thesis, and whether the latest simulated execution looked favorable or unfavorable.
Research and probability views now expose evidence summaries and source-type contribution changes alongside factor drift.
Execution history and timeline views now expose simulated bid/ask context, fragment-level fills, latency, and expiry/cancel completion reasons.
Execution evaluation views summarize intended vs realized price, expected vs filled size, expected vs realized timing, intended completion vs actual completion reason, and assign a verdict such as better, within range, worse, expired, cancelled, or partially filled.
Outcome analysis views now expose grouped learning summaries across persisted decision reviews and execution evaluations, with cached snapshots for later inspection.
Alert inspection now includes lifecycle state, and saved views provide reusable operator filters for listings and grouped analyses.
The operator dashboard is presentation-only and reuses the same proposal, execution, notification, decision-review, and outcome-analysis services as the CLI.
UI alert actions call the same acknowledgment, dismissal, and resolution service methods used by the CLI; no alert mutation logic lives in the presentation layer.
Integrated decision-review pages now join proposal context, persisted probability snapshot, drift summary, latest intent, simulated execution outcome, and latest execution evaluation into a single operator view.
The production web UI now requires authentication before any operator page is reachable.
Web auth is currently single-user (`osokolin`) with a password configured out-of-band through `bot auth set-password`, a server-side session cookie, and an optional remember-browser cookie stored only in HttpOnly cookies.
Authenticated web mutations are CSRF-protected, and the `/auth/security` page allows the operator to log out, revoke the current browser remember token, or revoke all active sessions and remember tokens.
Web auth does not alter proposal, inbox, Telegram, or execution semantics; it only gates access to the existing UI.

## Opportunity Alerts

Discovery alerts are generated automatically by the background scanner.

Alerts appear when:
- a new relevant market is detected
- a relevant market has high liquidity
- a relevant market is resolving soon
- a relevant market already has system context

Alerts are delivered via:
- CLI
- Web UI
- Telegram notifications