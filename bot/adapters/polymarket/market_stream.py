from __future__ import annotations

from bot.adapters.polymarket.client import PolymarketClient, PolymarketParseError, _parse_datetime
from bot.domain.models import OrderBookSnapshot


class PolymarketOrderBookAdapter:
    def __init__(self, client: PolymarketClient) -> None:
        self.client = client

    def get_snapshot(self, market_id: str) -> OrderBookSnapshot:
        payload = self.client.get_orderbook(market_id)
        try:
            best_bid = float(payload["best_bid"])
            best_ask = float(payload["best_ask"])
            midpoint = round((best_bid + best_ask) / 2, 4)
            spread_pct = 0.0 if midpoint == 0 else round((best_ask - best_bid) / midpoint, 6)
            return OrderBookSnapshot(
                market_id=market_id,
                best_bid=best_bid,
                best_ask=best_ask,
                midpoint=midpoint,
                spread_pct=spread_pct,
                timestamp=_parse_datetime(payload["timestamp"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PolymarketParseError(f"Invalid order book payload for {market_id}") from exc
