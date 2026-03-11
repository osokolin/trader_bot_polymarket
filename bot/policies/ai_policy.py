from __future__ import annotations

from dataclasses import dataclass

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import BotMode
from bot.domain.enums import PolicyRejectionReason


@dataclass(slots=True)
class AIPolicy:
    def evaluate(self, settings: Settings, context) -> PolicyDecision:
        reasons: list[PolicyRejectionReason] = []
        details = {
            "confidence": context.probability.confidence,
            "model_agreement": context.probability.model_agreement,
            "source_types": [item.value for item in context.probability.source_types],
        }
        if context.probability.confidence < settings.entry_rules.min_confidence:
            reasons.append(PolicyRejectionReason.CONFIDENCE_BELOW_THRESHOLD)
        if context.edge < settings.entry_rules.min_edge_pct:
            reasons.append(PolicyRejectionReason.EDGE_BELOW_THRESHOLD)
        if context.probability.model_agreement < settings.entry_rules.min_model_agreement:
            reasons.append(PolicyRejectionReason.MODEL_AGREEMENT_TOO_LOW)
        if settings.entry_rules.require_trusted_source and not context.probability.trusted_source_present:
            reasons.append(PolicyRejectionReason.TRUSTED_SOURCE_REQUIRED)
        allowed_source_types = set(settings.ai_policy.allowed_source_types)
        if any(source_type not in allowed_source_types for source_type in context.probability.source_types):
            reasons.append(PolicyRejectionReason.SOURCE_TYPE_NOT_ALLOWED)
        if settings.mode == BotMode.SEMI_AUTO and settings.approvals.manual_approval_required:
            details["manual_approval_required"] = True
        if settings.ai_policy.ai_can_place_orders:
            details["ai_ordering_enabled"] = True
        return PolicyDecision(allowed=not reasons, reasons=reasons, details=details)
