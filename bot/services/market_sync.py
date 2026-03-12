from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.adapters.polymarket.clob_client import PolymarketOrderBookAdapter
from bot.adapters.polymarket.errors import PolymarketParseError, PolymarketStaleDataError
from bot.adapters.polymarket.gamma_client import PolymarketMarketMetadataAdapter
from bot.domain.models import MarketDataSnapshot
from bot.storage.repositories import MarketDataSnapshotRepository
from bot.utils.ids import new_id


@dataclass(slots=True)
class LiveMarketDataService:
    market_adapter: PolymarketMarketMetadataAdapter
    orderbook_adapter: PolymarketOrderBookAdapter
    snapshot_repository: MarketDataSnapshotRepository | None = None
    stale_after_seconds: int = 120

    def fetch_live_snapshot(self, market_id: str, source: str = "rest") -> MarketDataSnapshot:
        metadata = self.market_adapter.get_market_metadata(market_id)
        if not metadata.market.has_orderbook or not metadata.asset_id:
            raise PolymarketParseError("Live approval requires an orderbook-enabled market with an asset_id")
        orderbook = self.orderbook_adapter.get_orderbook(metadata.asset_id, market_id=market_id)
        observed_at = orderbook.snapshot.timestamp.astimezone(timezone.utc)
        data_age_seconds = max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))
        stale = data_age_seconds > self.stale_after_seconds
        if stale:
            raise PolymarketStaleDataError(
                f"Order book snapshot for {market_id} is stale: age={data_age_seconds}s > {self.stale_after_seconds}s"
            )
        snapshot = MarketDataSnapshot(
            snapshot_id=new_id("msnap"),
            market_id=market_id,
            asset_id=metadata.asset_id,
            market=metadata.market,
            orderbook=orderbook.snapshot,
            observed_at=observed_at,
            fetched_at=datetime.now(timezone.utc),
            source=source,
            stale=stale,
            data_age_seconds=data_age_seconds,
            reference_price=orderbook.reference_price if orderbook.reference_price is not None else metadata.market.last_traded_price,
            pricing_metadata=orderbook.pricing_metadata,
            websocket_payload={},
        )
        self.persist_snapshot(snapshot)
        return snapshot

    def latest_cached_snapshot(self, market_id: str, fail_on_stale: bool = False) -> MarketDataSnapshot | None:
        if self.snapshot_repository is None:
            return None
        snapshot = self.snapshot_repository.latest_for_market(market_id)
        if snapshot is None:
            return None
        current_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - snapshot.observed_at.astimezone(timezone.utc)).total_seconds()),
        )
        normalized = MarketDataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            market_id=snapshot.market_id,
            asset_id=snapshot.asset_id,
            market=snapshot.market,
            orderbook=snapshot.orderbook,
            observed_at=snapshot.observed_at,
            fetched_at=snapshot.fetched_at,
            source=snapshot.source,
            stale=current_age_seconds > self.stale_after_seconds,
            data_age_seconds=current_age_seconds,
            reference_price=snapshot.reference_price,
            pricing_metadata=snapshot.pricing_metadata,
            websocket_payload=snapshot.websocket_payload,
        )
        if fail_on_stale and normalized.stale:
            raise PolymarketStaleDataError(
                f"Cached market snapshot for {market_id} is stale: age={normalized.data_age_seconds}s"
            )
        return normalized

    def inspect_snapshot(self, market_id: str, refresh: bool = False) -> MarketDataSnapshot:
        if not refresh:
            cached = self.latest_cached_snapshot(market_id, fail_on_stale=False)
            if cached is not None:
                return cached
        return self.fetch_live_snapshot(market_id, source="inspection" if refresh else "rest")

    def list_cached_snapshots(self, market_id: str, limit: int = 20) -> list[MarketDataSnapshot]:
        if self.snapshot_repository is None:
            return []
        return self.snapshot_repository.list_for_market(market_id, limit=limit)

    def persist_snapshot(self, snapshot: MarketDataSnapshot) -> None:
        if self.snapshot_repository is None:
            return
        self.snapshot_repository.save(snapshot)
