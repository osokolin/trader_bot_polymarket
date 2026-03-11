from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from bot.config.models import (
    AIPolicyConfig,
    ApprovalsConfig,
    BankrollConfig,
    BlacklistConfig,
    EntryRulesConfig,
    ExitRulesConfig,
    MarketFiltersConfig,
    PositionLimitsConfig,
    SafetyConfig,
    Settings,
    SourcesConfig,
    WhitelistConfig,
)
from bot.domain.enums import BotMode, SourceType


class ConfigError(ValueError):
    pass


def parse_yaml(text: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError("Top-level YAML document must be a mapping")
    return parsed


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"Missing required config key: {key}")
    return data[key]


def _ensure_ratio(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ConfigError(f"{name} must be between 0 and 1")


def _ensure_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ConfigError(f"{name} must be positive")


def _ensure_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ConfigError(f"{name} must be non-negative")


def _validate_settings(settings: Settings) -> None:
    _ensure_positive("bankroll.total_usd", settings.bankroll.total_usd)
    _ensure_ratio("bankroll.reserve_ratio", settings.bankroll.reserve_ratio)
    _ensure_non_negative("bankroll.max_daily_loss_usd", settings.bankroll.max_daily_loss_usd)
    _ensure_non_negative("bankroll.max_weekly_loss_usd", settings.bankroll.max_weekly_loss_usd)
    if settings.bankroll.max_weekly_loss_usd < settings.bankroll.max_daily_loss_usd:
        raise ConfigError("bankroll.max_weekly_loss_usd must be >= bankroll.max_daily_loss_usd")

    _ensure_ratio("position_limits.max_position_pct", settings.position_limits.max_position_pct)
    _ensure_ratio("position_limits.max_theme_exposure_pct", settings.position_limits.max_theme_exposure_pct)
    _ensure_ratio("position_limits.max_unresolved_exposure_pct", settings.position_limits.max_unresolved_exposure_pct)
    if settings.position_limits.max_open_positions < 1:
        raise ConfigError("position_limits.max_open_positions must be >= 1")
    if settings.position_limits.max_position_pct > settings.position_limits.max_theme_exposure_pct:
        raise ConfigError("position_limits.max_position_pct must be <= position_limits.max_theme_exposure_pct")

    _ensure_non_negative("market_filters.min_liquidity_usd", settings.market_filters.min_liquidity_usd)
    _ensure_ratio("market_filters.max_spread_pct", settings.market_filters.max_spread_pct)
    _ensure_non_negative(
        "market_filters.min_time_to_resolution_hours",
        settings.market_filters.min_time_to_resolution_hours,
    )
    if not settings.market_filters.allowed_categories:
        raise ConfigError("market_filters.allowed_categories must not be empty")

    _ensure_ratio("entry_rules.min_edge_pct", settings.entry_rules.min_edge_pct)
    _ensure_ratio("entry_rules.min_confidence", settings.entry_rules.min_confidence)
    _ensure_ratio("entry_rules.max_price_jump_15m_pct", settings.entry_rules.max_price_jump_15m_pct)
    if settings.entry_rules.min_model_agreement < 1:
        raise ConfigError("entry_rules.min_model_agreement must be >= 1")

    _ensure_non_negative(
        "exit_rules.close_before_resolution_hours",
        settings.exit_rules.close_before_resolution_hours,
    )
    _ensure_ratio("exit_rules.take_profit_edge_collapse_pct", settings.exit_rules.take_profit_edge_collapse_pct)
    _ensure_ratio("exit_rules.stop_loss_prob_shift_pct", settings.exit_rules.stop_loss_prob_shift_pct)
    _ensure_non_negative("exit_rules.max_holding_hours", settings.exit_rules.max_holding_hours)

    _ensure_ratio("ai_policy.min_rules_parser_confidence", settings.ai_policy.min_rules_parser_confidence)
    _ensure_ratio("ai_policy.min_news_relevance_score", settings.ai_policy.min_news_relevance_score)
    if not settings.ai_policy.allowed_source_types:
        raise ConfigError("ai_policy.allowed_source_types must not be empty")

    _ensure_ratio("approvals.auto_execute_if_score_above", settings.approvals.auto_execute_if_score_above)
    if settings.approvals.proposal_ttl_minutes < 1:
        raise ConfigError("approvals.proposal_ttl_minutes must be >= 1")

    if settings.safety.pause_on_api_errors < 1:
        raise ConfigError("safety.pause_on_api_errors must be >= 1")
    if settings.safety.pause_on_consecutive_losses < 1:
        raise ConfigError("safety.pause_on_consecutive_losses must be >= 1")

    if settings.mode == BotMode.SEMI_AUTO and not settings.approvals.manual_approval_required:
        raise ConfigError("semi_auto mode requires approvals.manual_approval_required = true")
    if settings.mode == BotMode.SEMI_AUTO and not settings.approvals.auto_execute_disabled:
        raise ConfigError("semi_auto mode requires approvals.auto_execute_disabled = true")
    if settings.ai_policy.ai_can_place_orders and settings.approvals.auto_execute_disabled:
        raise ConfigError("ai_policy.ai_can_place_orders cannot be true while auto execution is disabled")


def _to_settings(
    data: dict[str, Any],
    sources: dict[str, Any],
    whitelist: dict[str, Any],
    blacklist: dict[str, Any],
) -> Settings:
    ai_policy_data = _require(data, "ai_policy")
    settings = Settings(
        mode=BotMode(_require(data, "mode")),
        bankroll=BankrollConfig(**_require(data, "bankroll")),
        position_limits=PositionLimitsConfig(**_require(data, "position_limits")),
        market_filters=MarketFiltersConfig(**_require(data, "market_filters")),
        entry_rules=EntryRulesConfig(**_require(data, "entry_rules")),
        exit_rules=ExitRulesConfig(**_require(data, "exit_rules")),
        ai_policy=AIPolicyConfig(
            ai_can_place_orders=ai_policy_data["ai_can_place_orders"],
            ai_can_only_score=ai_policy_data["ai_can_only_score"],
            min_rules_parser_confidence=ai_policy_data["min_rules_parser_confidence"],
            min_news_relevance_score=ai_policy_data["min_news_relevance_score"],
            allowed_source_types=[SourceType(item) for item in ai_policy_data["allowed_source_types"]],
        ),
        approvals=ApprovalsConfig(**_require(data, "approvals")),
        safety=SafetyConfig(**_require(data, "safety")),
        sources=SourcesConfig(**sources),
        whitelist=WhitelistConfig(**whitelist),
        blacklist=BlacklistConfig(**blacklist),
    )
    _validate_settings(settings)
    return settings


def load_settings(config_dir: Path, profile: str = "balanced") -> Settings:
    merged = _deep_merge(
        parse_yaml((config_dir / "base.yaml").read_text()),
        parse_yaml((config_dir / f"{profile}.yaml").read_text()),
    )
    if mode_override := os.getenv("BOT_MODE"):
        merged["mode"] = mode_override
    return _to_settings(
        merged,
        parse_yaml((config_dir / "sources.yaml").read_text()),
        parse_yaml((config_dir / "whitelist.yaml").read_text()),
        parse_yaml((config_dir / "blacklist.yaml").read_text()),
    )
