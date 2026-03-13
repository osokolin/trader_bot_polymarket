# Config Reference

This file documents every current configuration field used by Milestones 1 and 2.

## `mode`

- Purpose: selects the operating mode for the bot.
- Type: string enum (`paper`, `manual_only`, `semi_auto`, `live_small`, `live_full`)
- Example: `semi_auto`
- Lower/higher effect: not numeric; safer modes reduce automation.
- Interactions: `semi_auto` should be paired with `approvals.manual_approval_required: true`.

## `bankroll.total_usd`

- Purpose: base bankroll for position sizing and exposure checks.
- Type: float
- Example: `1000`
- Lower/higher effect: lower values reduce allowed sizes; higher values increase maximum size ceilings.
- Interactions: used with `position_limits.*` and `bankroll.reserve_ratio`.

## `bankroll.reserve_ratio`

- Purpose: portion of bankroll reserved from new trades.
- Type: float between `0` and `1`
- Example: `0.20`
- Lower/higher effect: lower values allow more capital deployment; higher values make the bot more conservative.
- Interactions: directly reduces size output in the sizing engine.

## `bankroll.max_daily_loss_usd`

- Purpose: hard daily loss cap for new entries.
- Type: float
- Example: `40`
- Lower/higher effect: lower values pause trading sooner; higher values tolerate more drawdown.
- Interactions: intended for safety enforcement and future live controls.

## `bankroll.max_weekly_loss_usd`

- Purpose: weekly loss cap for new entries.
- Type: float
- Example: `120`
- Lower/higher effect: lower values make weekly risk tighter; higher values permit larger cumulative losses.
- Interactions: complements `max_daily_loss_usd`.

## `position_limits.max_position_pct`

- Purpose: maximum bankroll share allocated to one position before sizing reductions.
- Type: float between `0` and `1`
- Example: `0.07`
- Lower/higher effect: lower values cap single-trade exposure more aggressively; higher values allow larger single positions.
- Interactions: primary ceiling for the sizing engine.

## `position_limits.max_theme_exposure_pct`

- Purpose: caps total exposure to one event/theme cluster.
- Type: float between `0` and `1`
- Example: `0.15`
- Lower/higher effect: lower values diversify more; higher values permit concentration.
- Interactions: sizing reduces recommended size when theme exposure is elevated.

## `position_limits.max_open_positions`

- Purpose: maximum concurrent positions.
- Type: integer
- Example: `4`
- Lower/higher effect: lower values reduce operational complexity and diversification; higher values permit broader coverage.
- Interactions: enforced by the risk policy.

## `position_limits.max_unresolved_exposure_pct`

- Purpose: caps bankroll locked in unresolved markets.
- Type: float between `0` and `1`
- Example: `0.35`
- Lower/higher effect: lower values protect liquidity; higher values allow more capital to remain tied up.
- Interactions: enforced by both sizing and risk policy.

## `market_filters.allowed_categories`

- Purpose: categories the bot may consider.
- Type: list of strings
- Example: `["politics", "crypto"]`
- Lower/higher effect: more entries broaden scan scope.
- Interactions: checked before blacklist/pattern rules.

## `market_filters.blocked_categories`

- Purpose: categories the bot must reject.
- Type: list of strings
- Example: `["sports"]`
- Lower/higher effect: more entries make the policy stricter.
- Interactions: takes precedence over general strategy interest.

## `market_filters.min_liquidity_usd`

- Purpose: minimum liquidity for tradable markets.
- Type: float
- Example: `3000`
- Lower/higher effect: lower values admit thinner markets; higher values prefer easier execution.
- Interactions: used by market policy and sizing adjustments.

## `market_filters.max_spread_pct`

- Purpose: maximum allowed bid/ask spread.
- Type: float
- Example: `0.03`
- Lower/higher effect: lower values improve execution quality but reject more markets; higher values increase fill flexibility.
- Interactions: enforced by market policy.

## `market_filters.min_time_to_resolution_hours`

- Purpose: minimum time remaining before market resolution.
- Type: float
- Example: `24`
- Lower/higher effect: lower values allow later entries; higher values avoid near-deadline risk.
- Interactions: enforced by market policy.

## `market_filters.require_clear_rules`

- Purpose: require unambiguous market rules.
- Type: boolean
- Example: `true`
- Lower/higher effect: `false` increases coverage but weakens safety.
- Interactions: used with `ai_policy.min_rules_parser_confidence`.

## `market_filters.require_orderbook`

- Purpose: require order book support for controlled limit execution.
- Type: boolean
- Example: `true`
- Lower/higher effect: `false` allows less structured venues.
- Interactions: aligns with `entry_rules.order_type`.

## `entry_rules.min_edge_pct`

- Purpose: minimum fair-value edge needed for entry.
- Type: float
- Example: `0.05`
- Lower/higher effect: lower values create more proposals; higher values create fewer but stronger candidates.
- Interactions: combined with confidence in proposal scoring and sizing.

## `entry_rules.min_confidence`

- Purpose: minimum model confidence for entry.
- Type: float
- Example: `0.70`
- Lower/higher effect: lower values allow noisier signals; higher values require stronger evidence.
- Interactions: enforced by AI policy and used by sizing.

## `entry_rules.min_model_agreement`

- Purpose: minimum count of independent supporting signals.
- Type: integer
- Example: `2`
- Lower/higher effect: lower values allow more speculative trades; higher values require consensus.
- Interactions: enforced by AI policy.

## `entry_rules.require_trusted_source`

- Purpose: require at least one trusted source in the signal set.
- Type: boolean
- Example: `true`
- Lower/higher effect: `false` allows weaker source provenance.
- Interactions: enforced by AI policy using `ai_policy.allowed_source_types`.

## `entry_rules.max_price_jump_15m_pct`

- Purpose: blocks chasing sharp recent moves.
- Type: float
- Example: `0.08`
- Lower/higher effect: lower values are stricter on momentum spikes; higher values tolerate more recent price movement.
- Interactions: intended for execution checks in later milestones.

## `entry_rules.order_type`

- Purpose: restricts allowed order type.
- Type: string
- Example: `limit_only`
- Lower/higher effect: not numeric; stricter values reduce execution flexibility.
- Interactions: enforced by execution policy.

## `exit_rules.close_before_resolution_hours`

- Purpose: force-close ahead of resolution.
- Type: float
- Example: `12`
- Lower/higher effect: lower values hold longer; higher values exit earlier.
- Interactions: consumed by later position monitoring logic.

## `exit_rules.take_profit_edge_collapse_pct`

- Purpose: exit threshold when edge collapses.
- Type: float
- Example: `0.02`
- Lower/higher effect: lower values realize profits sooner; higher values hold longer.
- Interactions: future exit proposal logic.

## `exit_rules.stop_loss_prob_shift_pct`

- Purpose: exit threshold when model probability worsens.
- Type: float
- Example: `0.06`
- Lower/higher effect: lower values stop out faster; higher values tolerate more thesis drift.
- Interactions: future monitoring logic.

## `exit_rules.max_holding_hours`

- Purpose: time stop for open positions.
- Type: float
- Example: `72`
- Lower/higher effect: lower values shorten holding duration; higher values keep capital locked longer.
- Interactions: future position monitor behavior.

## `ai_policy.ai_can_place_orders`

- Purpose: whether AI may place orders directly.
- Type: boolean
- Example: `false`
- Lower/higher effect: `true` weakens safety and is disabled in current defaults.
- Interactions: must remain `false` for policy-first semi-auto operation.

## `ai_policy.ai_can_only_score`

- Purpose: whether AI is limited to scoring/explanations.
- Type: boolean
- Example: `true`
- Lower/higher effect: `true` keeps AI advisory-only.
- Interactions: complements `ai_can_place_orders`.

## `ai_policy.min_rules_parser_confidence`

- Purpose: minimum confidence for interpreting market rules.
- Type: float
- Example: `0.80`
- Lower/higher effect: lower values admit ambiguous rules; higher values reject more uncertain markets.
- Interactions: used when `market_filters.require_clear_rules` is enabled.

## `ai_policy.min_news_relevance_score`

- Purpose: minimum relevance for news-driven signals.
- Type: float
- Example: `0.75`
- Lower/higher effect: lower values accept weaker news matches; higher values demand tighter relevance.
- Interactions: used by the AI policy when news signals are present.

## `ai_policy.allowed_source_types`

- Purpose: trusted source classes that satisfy source requirements.
- Type: list of enums
- Example: `["official", "regulator", "major_media"]`
- Lower/higher effect: more entries increase eligible source coverage.
- Interactions: checked against signal provenance.

## `approvals.manual_approval_required`

- Purpose: require human approval before execution.
- Type: boolean
- Example: `true`
- Lower/higher effect: `true` is mandatory for current `semi_auto` defaults.
- Interactions: must stay `true` when `mode` is `semi_auto`.

## `approvals.auto_execute_if_score_above`

- Purpose: reserved threshold for future auto-execution paths.
- Type: float
- Example: `0.90`
- Lower/higher effect: lower values would make auto-execution easier if enabled.
- Interactions: currently superseded by `auto_execute_disabled`.

## `approvals.auto_execute_disabled`

- Purpose: global block on auto-execution.
- Type: boolean
- Example: `true`
- Lower/higher effect: `true` is safest and currently required.
- Interactions: keeps live execution disabled even if score thresholds are met.

## `approvals.proposal_ttl_minutes`

- Purpose: time window for manual approval validity.
- Type: integer
- Example: `5`
- Lower/higher effect: lower values force fresher proposals; higher values reduce operational friction.
- Interactions: proposal engine uses this to set proposal expiry.

## `safety.kill_switch_enabled`

- Purpose: master permission for opening new positions.
- Type: boolean
- Example: `true`
- Lower/higher effect: `false` blocks proposals from being allowed.
- Interactions: enforced by execution policy.

## `safety.pause_on_api_errors`

- Purpose: threshold for pausing after repeated API errors.
- Type: integer
- Example: `3`
- Lower/higher effect: lower values pause earlier; higher values tolerate more instability.
- Interactions: future runtime safety controller.

## `safety.pause_on_consecutive_losses`

- Purpose: threshold for pausing after repeated losing trades.
- Type: integer
- Example: `4`
- Lower/higher effect: lower values are more conservative.
- Interactions: future live/paper monitoring.

## `safety.pause_on_unexpected_position_state`

- Purpose: pause when exchange and local state diverge.
- Type: boolean
- Example: `true`
- Lower/higher effect: `true` improves operational safety.
- Interactions: future execution and reconciliation logic.

