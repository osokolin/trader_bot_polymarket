from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import PolicyRejectionReason


@dataclass(slots=True)
class ExecutionPolicy:
    stale_after_seconds: int = 120

    def evaluate(self, settings: Settings, context) -> PolicyDecision:
        reasons: list[PolicyRejectionReason] = []
        details = {"data_age_seconds": context.data_age_seconds, "order_type": context.order_type}
        if not settings.safety.kill_switch_enabled:
            reasons.append(PolicyRejectionReason.KILL_SWITCH_ACTIVE)
        if context.order_type != settings.entry_rules.order_type:
            reasons.append(PolicyRejectionReason.ORDER_TYPE_NOT_ALLOWED)
        if context.data_age_seconds > self.stale_after_seconds:
            reasons.append(PolicyRejectionReason.STALE_DATA)
        return PolicyDecision(allowed=not reasons, reasons=reasons, details=details)

