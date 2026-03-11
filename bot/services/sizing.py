from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.utils.math import clamp


@dataclass(slots=True)
class SizingInput:
    confidence: float
    min_confidence: float
    edge: float
    min_edge: float
    theme_exposure_usd: float
    unresolved_exposure_usd: float
    liquidity_usd: float


@dataclass(slots=True)
class SizingResult:
    recommended_size_usd: float
    max_allowed_size_usd: float
    explanation: list[str]


class SizingEngine:
    def size(self, settings: Settings, data: SizingInput) -> SizingResult:
        bankroll = settings.bankroll.total_usd
        base_size = bankroll * settings.position_limits.max_position_pct
        reserve_capital = bankroll * (1 - settings.bankroll.reserve_ratio)
        unresolved_cap = bankroll * settings.position_limits.max_unresolved_exposure_pct
        max_allowed_size = min(
            base_size,
            reserve_capital,
            max(0.0, unresolved_cap - data.unresolved_exposure_usd),
        )
        explanation = [f"base_size={base_size:.2f}"]

        confidence_ratio = clamp(
            (data.confidence - data.min_confidence) / max(0.01, 1 - data.min_confidence),
            0.25,
            1.0,
        )
        size = max_allowed_size * confidence_ratio
        explanation.append(f"confidence_multiplier={confidence_ratio:.2f}")

        edge_ratio = clamp(data.edge / max(data.min_edge, 0.01), 0.5, 1.25)
        size *= min(edge_ratio, 1.0)
        explanation.append(f"edge_multiplier={min(edge_ratio, 1.0):.2f}")

        theme_cap = bankroll * settings.position_limits.max_theme_exposure_pct
        if data.theme_exposure_usd > 0:
            remaining_theme_room = max(0.0, theme_cap - data.theme_exposure_usd)
            size = min(size, remaining_theme_room)
            explanation.append(f"theme_room={remaining_theme_room:.2f}")

        if data.liquidity_usd < settings.market_filters.min_liquidity_usd * 1.5:
            size *= 0.75
            explanation.append("liquidity_penalty=0.75")

        size = round(max(0.0, min(size, max_allowed_size)), 2)
        max_allowed_size = round(max_allowed_size, 2)
        explanation.append(f"final_size={size:.2f}")
        return SizingResult(size, max_allowed_size, explanation)

