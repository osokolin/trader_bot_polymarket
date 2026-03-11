from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bot.domain.models import EvidenceRecord, Market, OrderBookSnapshot, ProbabilityEstimate, TradeProposal
from bot.utils.math import clamp


class ProbabilityProvider(Protocol):
    def get_probability(
        self,
        proposal: TradeProposal,
        market: Market,
        orderbook: OrderBookSnapshot,
    ) -> ProbabilityEstimate:
        ...


@dataclass(slots=True)
class EdgeAdjustedProbabilityProvider:
    def get_probability(
        self,
        proposal: TradeProposal,
        market: Market,
        orderbook: OrderBookSnapshot,
    ) -> ProbabilityEstimate:
        preserved_edge = proposal.fair_probability - proposal.market_price
        fair_probability = clamp(orderbook.midpoint + preserved_edge, 0.0, 1.0)
        evidence_records = []
        source_type_contributions: dict[str, float] = {}
        if proposal.source_types:
            equal_weight = round(1.0 / len(proposal.source_types), 4)
            for index, item in enumerate(proposal.source_types, start=1):
                contribution = round(proposal.confidence * equal_weight, 4)
                evidence_records.append(
                    EvidenceRecord(
                        source_id=f"{item.value}_{index}",
                        source_name=f"{item.value}_source_{index}",
                        source_type=item,
                        weight=equal_weight,
                        contribution=contribution,
                        summary=f"{item.value} input preserved through midpoint-based revalidation.",
                        supports_trade=True,
                    )
                )
                source_type_contributions[item.value] = round(
                    source_type_contributions.get(item.value, 0.0) + contribution,
                    4,
                )
        return ProbabilityEstimate(
            market_id=market.market_id,
            fair_probability=round(fair_probability, 4),
            confidence=proposal.confidence,
            model_agreement=proposal.model_agreement,
            trusted_source_present=proposal.trusted_source_present,
            source_types=proposal.source_types,
            key_factors=[
                f"preserved_edge={preserved_edge:.4f}",
                f"orderbook_midpoint={orderbook.midpoint:.4f}",
            ],
            source_count=len(proposal.source_types),
            confidence_components={
                "prior_confidence": proposal.confidence,
                "liquidity_component": min(1.0, market.liquidity_usd / 10000),
                "spread_component": max(0.0, 1 - orderbook.spread_pct),
            },
            explanation="Adjusted prior fair probability by preserving the proposal edge against the fresh midpoint.",
            source_inputs=[
                {"type": item.value, "trusted": proposal.trusted_source_present}
                for item in proposal.source_types
            ],
            evidence_records=evidence_records,
            source_type_contributions=source_type_contributions,
        )
