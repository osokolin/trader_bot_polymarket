from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.adapters.polymarket.errors import PolymarketAdapterError, PolymarketStaleDataError
from bot.adapters.polymarket.websocket_market import PublicMarketWebSocketClient
from bot.domain.models import MarketDataSnapshot, OrderBookSnapshot
from bot.services.market_sync import LiveMarketDataService
from bot.utils.ids import new_id


@dataclass(slots=True)
class RealtimeMarketFeedService:
    market_sync_service: LiveMarketDataService
    websocket_client: PublicMarketWebSocketClient
    stale_after_seconds: int = 120

    async def refresh_from_websocket(self, market_id: str, max_messages: int = 1) -> MarketDataSnapshot:
        baseline = self.market_sync_service.fetch_live_snapshot(market_id, source="rest")
        updates = await self.websocket_client.stream_market([baseline.asset_id], max_messages=max_messages)
        if not updates:
            raise PolymarketAdapterError(f"No WebSocket market updates received for {market_id}")
        latest = updates[-1]
        observed_at = latest.timestamp.astimezone(timezone.utc)
        data_age_seconds = max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))
        stale = data_age_seconds > self.stale_after_seconds
        if stale:
            raise PolymarketStaleDataError(
                f"WebSocket market update for {market_id} is stale: age={data_age_seconds}s > {self.stale_after_seconds}s"
            )
        pricing_metadata = dict(baseline.pricing_metadata)
        if latest.reference_price is not None:
            pricing_metadata["reference_price_source"] = "websocket"
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
            observed_at=observed_at,
            fetched_at=datetime.now(timezone.utc),
            source="websocket",
            stale=stale,
            data_age_seconds=data_age_seconds,
            reference_price=latest.reference_price if latest.reference_price is not None else baseline.reference_price,
            pricing_metadata=pricing_metadata,
            websocket_payload=latest.raw_payload,
        )
        self.market_sync_service.persist_snapshot(snapshot)
        return snapshot
