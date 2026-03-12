from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bot.domain.models import Market, OrderBookSnapshot, ProbabilityEstimate, TradeProposal
from bot.services.market_sync import LiveMarketDataService
from bot.services.probability_engine import ProbabilityProvider


@dataclass(slots=True)
class RevalidationSnapshot:
    market: Market
    probability: ProbabilityEstimate
    orderbook: OrderBookSnapshot | None
    current_price: float
    data_age_seconds: int
    market_snapshot_id: str | None = None
    reference_price: float | None = None
    snapshot_source: str | None = None
    pricing_metadata: dict[str, object] | None = None


class ApprovalSnapshotProvider(Protocol):
    def get_snapshot(self, proposal: TradeProposal) -> RevalidationSnapshot:
        ...


class PolymarketApprovalSnapshotProvider:
    def __init__(self, market_data_service: LiveMarketDataService, probability_provider: ProbabilityProvider) -> None:
        self.market_data_service = market_data_service
        self.probability_provider = probability_provider

    def get_snapshot(self, proposal: TradeProposal) -> RevalidationSnapshot:
        snapshot = self.market_data_service.fetch_live_snapshot(proposal.market_id, source="approval")
        probability = self.probability_provider.get_probability(proposal, snapshot.market, snapshot.orderbook)
        return RevalidationSnapshot(
            market=snapshot.market,
            probability=probability,
            orderbook=snapshot.orderbook,
            current_price=snapshot.orderbook.midpoint,
            data_age_seconds=snapshot.data_age_seconds,
            market_snapshot_id=snapshot.snapshot_id,
            reference_price=snapshot.reference_price,
            snapshot_source=snapshot.source,
            pricing_metadata=snapshot.pricing_metadata,
        )
