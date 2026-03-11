from __future__ import annotations

from dataclasses import dataclass, field

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.policies.ai_policy import AIPolicy
from bot.policies.execution_policy import ExecutionPolicy
from bot.policies.market_policy import MarketPolicy
from bot.policies.risk_policy import RiskPolicy


@dataclass(slots=True)
class CompositePolicy:
    market_policy: MarketPolicy = field(default_factory=MarketPolicy)
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    ai_policy: AIPolicy = field(default_factory=AIPolicy)

    def evaluate(self, settings: Settings, context) -> PolicyDecision:
        decisions = {
            "market_policy": self.market_policy.evaluate(settings, context),
            "risk_policy": self.risk_policy.evaluate(settings, context),
            "execution_policy": self.execution_policy.evaluate(settings, context),
            "ai_policy": self.ai_policy.evaluate(settings, context),
        }
        reasons = []
        details = {}
        for name, decision in decisions.items():
            reasons.extend(decision.reasons)
            details[name] = decision.details
        return PolicyDecision(allowed=not reasons, reasons=reasons, details=details)
