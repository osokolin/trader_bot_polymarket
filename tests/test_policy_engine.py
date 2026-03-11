from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from bot.config.loader import load_settings
from bot.domain.enums import PolicyRejectionReason, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.policies.composite_policy import CompositePolicy
from bot.utils.time import utc_now


@dataclass
class PolicyContext:
    market: Market
    probability: ProbabilityEstimate
    proposed_size_usd: float
    open_positions: int
    unresolved_exposure_usd: float
    theme_exposure_usd: float
    order_type: str
    data_age_seconds: int
    now: object
    edge: float


class PolicyEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        self.policy = CompositePolicy()
        now = utc_now()
        self.market = Market(
            market_id="mkt_1",
            title="Will Congress pass the bill?",
            category="politics",
            liquidity_usd=8000,
            spread_pct=0.01,
            resolution_time=now + timedelta(days=4),
            rules_text="Clear rules",
            rules_confidence=0.95,
            tags=["politics"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_1",
            fair_probability=0.61,
            confidence=0.82,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
        )
        self.now = now

    def test_kill_switch_blocks_allowed_trade(self) -> None:
        self.settings.safety.kill_switch_enabled = False
        decision = self.policy.evaluate(
            self.settings,
            PolicyContext(
                market=self.market,
                probability=self.probability,
                proposed_size_usd=20,
                open_positions=0,
                unresolved_exposure_usd=0,
                theme_exposure_usd=0,
                order_type="limit_only",
                data_age_seconds=10,
                now=self.now,
                edge=0.08,
            ),
        )
        self.assertFalse(decision.allowed)
        self.assertIn(PolicyRejectionReason.KILL_SWITCH_ACTIVE, decision.reasons)

    def test_policy_collects_multiple_rejection_reasons(self) -> None:
        self.market.category = "sports"
        self.market.spread_pct = 0.09
        self.market.liquidity_usd = 200
        self.probability.confidence = 0.4
        self.probability.model_agreement = 1
        self.probability.trusted_source_present = False
        self.probability.source_types = [SourceType.SOCIAL]
        decision = self.policy.evaluate(
            self.settings,
            PolicyContext(
                market=self.market,
                probability=self.probability,
                proposed_size_usd=500,
                open_positions=10,
                unresolved_exposure_usd=600,
                theme_exposure_usd=500,
                order_type="market",
                data_age_seconds=600,
                now=self.now,
                edge=0.01,
            ),
        )
        self.assertFalse(decision.allowed)
        self.assertIn(PolicyRejectionReason.MARKET_CATEGORY_BLOCKED, decision.reasons)
        self.assertIn(PolicyRejectionReason.SPREAD_TOO_WIDE, decision.reasons)
        self.assertIn(PolicyRejectionReason.LIQUIDITY_TOO_LOW, decision.reasons)
        self.assertIn(PolicyRejectionReason.CONFIDENCE_BELOW_THRESHOLD, decision.reasons)
        self.assertIn(PolicyRejectionReason.UNRESOLVED_EXPOSURE_TOO_HIGH, decision.reasons)
        self.assertIn(PolicyRejectionReason.ORDER_TYPE_NOT_ALLOWED, decision.reasons)

    def test_policy_details_are_namespaced_by_layer(self) -> None:
        decision = self.policy.evaluate(
            self.settings,
            PolicyContext(
                market=self.market,
                probability=self.probability,
                proposed_size_usd=20,
                open_positions=0,
                unresolved_exposure_usd=0,
                theme_exposure_usd=0,
                order_type="limit_only",
                data_age_seconds=10,
                now=self.now,
                edge=0.08,
            ),
        )
        self.assertIn("market_policy", decision.details)
        self.assertIn("risk_policy", decision.details)
        self.assertIn("execution_policy", decision.details)
        self.assertIn("ai_policy", decision.details)


if __name__ == "__main__":
    unittest.main()
