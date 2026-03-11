from __future__ import annotations

from typing import Protocol

from bot.config.models import Settings
from bot.domain.decisions import PolicyDecision
from bot.domain.models import Market, ProbabilityEstimate


class PolicyInput(Protocol):
    market: Market
    probability: ProbabilityEstimate
    proposed_size_usd: float
    open_positions: int
    unresolved_exposure_usd: float
    theme_exposure_usd: float
    order_type: str
    data_age_seconds: int


class Policy(Protocol):
    def evaluate(self, settings: Settings, context: PolicyInput) -> PolicyDecision:
        ...

