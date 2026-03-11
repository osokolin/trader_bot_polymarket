from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import PolicyRejectionReason


@dataclass(slots=True)
class RiskPolicy:
    def evaluate(self, settings: Settings, context) -> PolicyDecision:
        reasons: list[PolicyRejectionReason] = []
        details = {
            "open_positions": context.open_positions,
            "unresolved_exposure_usd": context.unresolved_exposure_usd,
            "theme_exposure_usd": context.theme_exposure_usd,
        }
        limits = settings.position_limits
        bankroll = settings.bankroll.total_usd
        if context.open_positions >= limits.max_open_positions:
            reasons.append(PolicyRejectionReason.TOO_MANY_OPEN_POSITIONS)
        if context.unresolved_exposure_usd + context.proposed_size_usd > bankroll * limits.max_unresolved_exposure_pct:
            reasons.append(PolicyRejectionReason.UNRESOLVED_EXPOSURE_TOO_HIGH)
        if context.theme_exposure_usd + context.proposed_size_usd > bankroll * limits.max_theme_exposure_pct:
            reasons.append(PolicyRejectionReason.THEME_EXPOSURE_TOO_HIGH)
        if context.proposed_size_usd > bankroll * limits.max_position_pct:
            reasons.append(PolicyRejectionReason.PROPOSAL_SIZE_EXCEEDS_LIMIT)
        return PolicyDecision(allowed=not reasons, reasons=reasons, details=details)

