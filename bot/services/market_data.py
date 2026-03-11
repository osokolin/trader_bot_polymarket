from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from bot.adapters.polymarket.client import PolymarketAdapterError, PolymarketMarketMetadataAdapter
from bot.adapters.polymarket.market_stream import PolymarketOrderBookAdapter
from bot.domain.models import Market, OrderBookSnapshot, ProbabilityEstimate, TradeProposal
from bot.services.probability_engine import ProbabilityProvider


@dataclass(slots=True)
class RevalidationSnapshot:
    market: Market
    probability: ProbabilityEstimate
    orderbook: OrderBookSnapshot | None
    current_price: float
    data_age_seconds: int


class ApprovalSnapshotProvider(Protocol):
    def get_snapshot(self, proposal: TradeProposal) -> RevalidationSnapshot:
        ...


class PolymarketApprovalSnapshotProvider:
    def __init__(
        self,
        market_adapter: PolymarketMarketMetadataAdapter,
        orderbook_adapter: PolymarketOrderBookAdapter,
        probability_provider: ProbabilityProvider,
    ) -> None:
        self.market_adapter = market_adapter
        self.orderbook_adapter = orderbook_adapter
        self.probability_provider = probability_provider

    def get_snapshot(self, proposal: TradeProposal) -> RevalidationSnapshot:
        try:
            market = self.market_adapter.get_market(proposal.market_id)
            orderbook = self.orderbook_adapter.get_snapshot(proposal.market_id)
        except PolymarketAdapterError:
            raise
        current_price = orderbook.midpoint
        data_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - orderbook.timestamp.astimezone(timezone.utc)).total_seconds()),
        )
        probability = self.probability_provider.get_probability(proposal, market, orderbook)
        return RevalidationSnapshot(
            market=market,
            probability=probability,
            orderbook=orderbook,
            current_price=current_price,
            data_age_seconds=data_age_seconds,
        )
