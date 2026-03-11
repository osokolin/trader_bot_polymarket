from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import PolicyRejectionReason


@dataclass(slots=True)
class MarketPolicy:
    def evaluate(self, settings: Settings, context) -> PolicyDecision:
        reasons: list[PolicyRejectionReason] = []
        details: dict[str, object] = {
            "spread_pct": context.market.spread_pct,
            "liquidity_usd": context.market.liquidity_usd,
        }
        filters = settings.market_filters
        whitelist = settings.whitelist
        blacklist = settings.blacklist
        if context.market.category in filters.blocked_categories:
            reasons.append(PolicyRejectionReason.MARKET_CATEGORY_BLOCKED)
        if context.market.category not in filters.allowed_categories:
            reasons.append(PolicyRejectionReason.MARKET_NOT_WHITELISTED)
        if whitelist.allowed_market_ids and context.market.market_id not in whitelist.allowed_market_ids:
            reasons.append(PolicyRejectionReason.MARKET_NOT_WHITELISTED)
        if blacklist.blocked_market_ids and context.market.market_id in blacklist.blocked_market_ids:
            reasons.append(PolicyRejectionReason.MARKET_BLACKLISTED)
        if any(pattern.lower() in context.market.title.lower() for pattern in blacklist.blocked_patterns):
            reasons.append(PolicyRejectionReason.MARKET_BLACKLISTED)
        if context.market.liquidity_usd < filters.min_liquidity_usd:
            reasons.append(PolicyRejectionReason.LIQUIDITY_TOO_LOW)
        if context.market.spread_pct > filters.max_spread_pct:
            reasons.append(PolicyRejectionReason.SPREAD_TOO_WIDE)
        remaining = context.market.resolution_time - context.now
        if remaining < timedelta(hours=filters.min_time_to_resolution_hours):
            reasons.append(PolicyRejectionReason.TIME_TO_RESOLUTION_TOO_SHORT)
        if filters.require_clear_rules and context.market.rules_confidence < settings.ai_policy.min_rules_parser_confidence:
            reasons.append(PolicyRejectionReason.RULES_UNCLEAR)
        if filters.require_orderbook and not context.market.has_orderbook:
            reasons.append(PolicyRejectionReason.ORDERBOOK_REQUIRED)
        return PolicyDecision(allowed=not reasons, reasons=reasons, details=details)
