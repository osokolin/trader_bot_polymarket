from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.models import (
    Market,
    MarketDataSnapshot,
    OrderBookSnapshot,
)

class MarketDataSnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: MarketDataSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO market_data_snapshots (
                snapshot_id, market_id, asset_id, source, market_payload_json, orderbook_payload_json,
                websocket_payload_json, observed_at, stale, reference_price, pricing_metadata_json,
                data_age_seconds, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.market_id,
                snapshot.asset_id,
                snapshot.source,
                json.dumps(self._market_payload(snapshot.market)),
                json.dumps(self._orderbook_payload(snapshot.orderbook)),
                json.dumps(snapshot.websocket_payload),
                snapshot.observed_at.isoformat(),
                1 if snapshot.stale else 0,
                snapshot.reference_price,
                json.dumps(snapshot.pricing_metadata, sort_keys=True),
                snapshot.data_age_seconds,
                snapshot.fetched_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_market(self, market_id: str) -> MarketDataSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM market_data_snapshots
            WHERE market_id = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_for_market(self, market_id: str, limit: int = 20) -> list[MarketDataSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM market_data_snapshots
            WHERE market_id = ?
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (market_id, limit),
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> MarketDataSnapshot:
        market_payload = json.loads(row["market_payload_json"])
        orderbook_payload = json.loads(row["orderbook_payload_json"])
        return MarketDataSnapshot(
            snapshot_id=row["snapshot_id"],
            market_id=row["market_id"],
            asset_id=row["asset_id"],
            market=Market(
                market_id=market_payload["market_id"],
                title=market_payload["title"],
                category=market_payload["category"],
                liquidity_usd=market_payload["liquidity_usd"],
                spread_pct=market_payload["spread_pct"],
                resolution_time=datetime.fromisoformat(market_payload["resolution_time"]),
                rules_text=market_payload["rules_text"],
                rules_confidence=market_payload["rules_confidence"],
                tags=market_payload["tags"],
                has_orderbook=market_payload["has_orderbook"],
                event_id=market_payload.get("event_id"),
                outcome_token_id=market_payload.get("outcome_token_id"),
                active=market_payload.get("active", True),
                closed=market_payload.get("closed", False),
                archived=market_payload.get("archived", False),
                last_traded_price=market_payload.get("last_traded_price"),
            ),
            orderbook=OrderBookSnapshot(
                market_id=orderbook_payload["market_id"],
                best_bid=orderbook_payload["best_bid"],
                best_ask=orderbook_payload["best_ask"],
                midpoint=orderbook_payload["midpoint"],
                spread_pct=orderbook_payload["spread_pct"],
                timestamp=datetime.fromisoformat(orderbook_payload["timestamp"]),
            ),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            source=row["source"],
            stale=bool(row["stale"]),
            data_age_seconds=row["data_age_seconds"],
            reference_price=row["reference_price"],
            pricing_metadata=json.loads(row["pricing_metadata_json"]),
            websocket_payload=json.loads(row["websocket_payload_json"]),
        )

    def _market_payload(self, market: Market) -> dict[str, object]:
        return {
            "market_id": market.market_id,
            "title": market.title,
            "category": market.category,
            "liquidity_usd": market.liquidity_usd,
            "spread_pct": market.spread_pct,
            "resolution_time": market.resolution_time.isoformat(),
            "rules_text": market.rules_text,
            "rules_confidence": market.rules_confidence,
            "tags": market.tags,
            "has_orderbook": market.has_orderbook,
            "event_id": market.event_id,
            "outcome_token_id": market.outcome_token_id,
            "active": market.active,
            "closed": market.closed,
            "archived": market.archived,
            "last_traded_price": market.last_traded_price,
        }

    def _orderbook_payload(self, orderbook: OrderBookSnapshot) -> dict[str, object]:
        return {
            "market_id": orderbook.market_id,
            "best_bid": orderbook.best_bid,
            "best_ask": orderbook.best_ask,
            "midpoint": orderbook.midpoint,
            "spread_pct": orderbook.spread_pct,
            "timestamp": orderbook.timestamp.isoformat(),
        }
