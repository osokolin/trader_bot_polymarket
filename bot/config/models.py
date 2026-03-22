from __future__ import annotations

from dataclasses import dataclass

from bot.domain.enums import BotMode, SourceType


@dataclass(slots=True)
class BankrollConfig:
    total_usd: float
    reserve_ratio: float
    max_daily_loss_usd: float
    max_weekly_loss_usd: float


@dataclass(slots=True)
class PositionLimitsConfig:
    max_position_pct: float
    max_theme_exposure_pct: float
    max_open_positions: int
    max_unresolved_exposure_pct: float


@dataclass(slots=True)
class MarketFiltersConfig:
    allowed_categories: list[str]
    blocked_categories: list[str]
    min_liquidity_usd: float
    max_spread_pct: float
    min_time_to_resolution_hours: float
    require_clear_rules: bool
    require_orderbook: bool


@dataclass(slots=True)
class EntryRulesConfig:
    min_edge_pct: float
    min_confidence: float
    min_model_agreement: int
    require_trusted_source: bool
    max_price_jump_15m_pct: float
    order_type: str


@dataclass(slots=True)
class ExitRulesConfig:
    close_before_resolution_hours: float
    take_profit_edge_collapse_pct: float
    stop_loss_prob_shift_pct: float
    max_holding_hours: float


@dataclass(slots=True)
class AIPolicyConfig:
    ai_can_place_orders: bool
    ai_can_only_score: bool
    min_rules_parser_confidence: float
    min_news_relevance_score: float
    allowed_source_types: list[SourceType]


@dataclass(slots=True)
class ApprovalsConfig:
    manual_approval_required: bool
    auto_execute_if_score_above: float
    auto_execute_disabled: bool
    proposal_ttl_minutes: int


@dataclass(slots=True)
class SafetyConfig:
    kill_switch_enabled: bool
    pause_on_api_errors: int
    pause_on_consecutive_losses: int
    pause_on_unexpected_position_state: bool


@dataclass(slots=True)
class SourcesConfig:
    official_sources: list[str]
    regulator_sources: list[str]
    major_media_sources: list[str]


@dataclass(slots=True)
class WhitelistConfig:
    allowed_market_ids: list[str]
    allowed_tags: list[str]


@dataclass(slots=True)
class BlacklistConfig:
    blocked_market_ids: list[str]
    blocked_patterns: list[str]


@dataclass(slots=True)
class MarketOpportunityAlertsConfig:
    tracked_categories: list[str]
    tracked_keywords: list[str]
    liquidity_threshold: float
    resolving_soon_days: int
    poll_interval_seconds: int
    enabled_alert_types: list[str]


@dataclass(slots=True)
class PolymarketGatewayConfig:
    enable_polymarket_gateway: bool
    dry_run: bool
    gamma_base_url: str
    clob_base_url: str
    private_key_env_var: str
    api_key_env_var: str
    api_secret_env_var: str
    api_passphrase_env_var: str
    allow_live_order_submission: bool


@dataclass(slots=True)
class Settings:
    mode: BotMode
    bankroll: BankrollConfig
    position_limits: PositionLimitsConfig
    market_filters: MarketFiltersConfig
    entry_rules: EntryRulesConfig
    exit_rules: ExitRulesConfig
    ai_policy: AIPolicyConfig
    approvals: ApprovalsConfig
    safety: SafetyConfig
    sources: SourcesConfig
    whitelist: WhitelistConfig
    blacklist: BlacklistConfig
    market_opportunity_alerts: MarketOpportunityAlertsConfig
    polymarket_gateway: PolymarketGatewayConfig
