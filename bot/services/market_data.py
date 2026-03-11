from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from bot.adapters.polymarket.client import (
    PolymarketAdapterError,
    PolymarketMarketMetadataAdapter,
    PolymarketParseError,
    PolymarketStaleDataError,
)
from bot.adapters.polymarket.market_stream import PolymarketOrderBookAdapter, PublicMarketWebSocketClient
from bot.domain.models import Market, MarketDataSnapshot, OrderBookSnapshot, ProbabilityEstimate, TradeProposal
from bot.services.probability_engine import ProbabilityProvider
from bot.storage.repositories import MarketDataSnapshotRepository
from bot.utils.ids import new_id


@dataclass(slots=True)
class RevalidationSnapshot:
    market: Market
    probability: ProbabilityEstimate
    orderbook: OrderBookSnapshot | None
    current_price: float
    data_age_seconds: int
    market_snapshot_id: str | None = None
    last_trade_price: float | None = None
    snapshot_source: str | None = None


class ApprovalSnapshotProvider(Protocol):
    def get_snapshot(self, proposal: TradeProposal) -> RevalidationSnapshot:
        ...


class LiveMarketDataService:
    def __init__(
        self,
        market_adapter: PolymarketMarketMetadataAdapter,
        orderbook_adapter: PolymarketOrderBookAdapter,
        snapshot_repository: MarketDataSnapshotRepository | None = None,
        websocket_client: PublicMarketWebSocketClient | None = None,
        stale_after_seconds: int = 120,
    ) -> None:
        self.market_adapter = market_adapter
        self.orderbook_adapter = orderbook_adapter
        self.snapshot_repository = snapshot_repository
        self.websocket_client = websocket_client
        self.stale_after_seconds = stale_after_seconds

    def fetch_live_snapshot(self, market_id: str, source: str = "rest") -> MarketDataSnapshot:
        metadata = self.market_adapter.get_market_metadata(market_id)
        if not metadata.market.has_orderbook or not metadata.asset_id:
            raise PolymarketParseError("Live approval requires an orderbook-enabled market with an asset_id")
        orderbook = self.orderbook_adapter.get_orderbook(metadata.asset_id, market_id=market_id)
        data_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - orderbook.snapshot.timestamp.astimezone(timezone.utc)).total_seconds()),
        )
        if data_age_seconds > self.stale_after_seconds:
            raise PolymarketStaleDataError(
                f"Order book snapshot for {market_id} is stale: age={data_age_seconds}s > {self.stale_after_seconds}s"
            )
        snapshot = MarketDataSnapshot(
            snapshot_id=new_id("msnap"),
            market_id=market_id,
            asset_id=metadata.asset_id,
            market=metadata.market,
            orderbook=orderbook.snapshot,
            fetched_at=datetime.now(timezone.utc),
            source=source,
            data_age_seconds=data_age_seconds,
            last_trade_price=orderbook.last_trade_price if orderbook.last_trade_price is not None else metadata.market.last_traded_price,
            websocket_payload={},
        )
        self._persist(snapshot)
        return snapshot

    def refresh_from_websocket(self, market_id: str, max_messages: int = 1) -> MarketDataSnapshot:
        if self.websocket_client is None:
            raise PolymarketAdapterError("Public market WebSocket client is not configured")
        baseline = self.fetch_live_snapshot(market_id, source="rest")
        updates = asyncio.run(self.websocket_client.stream_market([baseline.asset_id], max_messages=max_messages))
        if not updates:
            raise PolymarketAdapterError(f"No WebSocket market updates received for {market_id}")
        latest = updates[-1]
        data_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - latest.timestamp.astimezone(timezone.utc)).total_seconds()),
        )
        if data_age_seconds > self.stale_after_seconds:
            raise PolymarketStaleDataError(
                f"WebSocket market update for {market_id} is stale: age={data_age_seconds}s > {self.stale_after_seconds}s"
            )
        snapshot = MarketDataSnapshot(
            snapshot_id=new_id("msnap"),
            market_id=baseline.market_id,
            asset_id=baseline.asset_id,
            market=baseline.market,
            orderbook=OrderBookSnapshot(
                market_id=baseline.market_id,
                best_bid=latest.best_bid,
                best_ask=latest.best_ask,
                midpoint=latest.midpoint,
                spread_pct=latest.spread_pct,
                timestamp=latest.timestamp,
            ),
            fetched_at=datetime.now(timezone.utc),
            source="websocket",
            data_age_seconds=data_age_seconds,
            last_trade_price=latest.last_trade_price,
            websocket_payload=latest.raw_payload,
        )
        self._persist(snapshot)
        return snapshot

    def latest_cached_snapshot(self, market_id: str, fail_on_stale: bool = False) -> MarketDataSnapshot | None:
        if self.snapshot_repository is None:
            return None
        snapshot = self.snapshot_repository.latest_for_market(market_id)
        if snapshot is None:
            return None
        current_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - snapshot.orderbook.timestamp.astimezone(timezone.utc)).total_seconds()),
        )
        snapshot = MarketDataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            market_id=snapshot.market_id,
            asset_id=snapshot.asset_id,
            market=snapshot.market,
            orderbook=snapshot.orderbook,
            fetched_at=snapshot.fetched_at,
            source=snapshot.source,
            data_age_seconds=current_age_seconds,
            last_trade_price=snapshot.last_trade_price,
            websocket_payload=snapshot.websocket_payload,
        )
        if fail_on_stale and snapshot.data_age_seconds > self.stale_after_seconds:
            raise PolymarketStaleDataError(
                f"Cached market snapshot for {market_id} is stale: age={snapshot.data_age_seconds}s"
            )
        return snapshot

    def list_cached_snapshots(self, market_id: str, limit: int = 20) -> list[MarketDataSnapshot]:
        if self.snapshot_repository is None:
            return []
        return self.snapshot_repository.list_for_market(market_id, limit=limit)

    def _persist(self, snapshot: MarketDataSnapshot) -> None:
        if self.snapshot_repository is None:
            return
        self.snapshot_repository.save(snapshot)


class PolymarketApprovalSnapshotProvider:
    def __init__(
        self,
        market_data_service: LiveMarketDataService,
        probability_provider: ProbabilityProvider,
    ) -> None:
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
            last_trade_price=snapshot.last_trade_price,
            snapshot_source=snapshot.source,
        )
