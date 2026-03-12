from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from bot.adapters.polymarket.errors import (
    PolymarketAdapterError,
    PolymarketHTTPError,
    PolymarketParseError,
    PolymarketTransportError,
)
from bot.adapters.polymarket.models import ClobOrderBook
from bot.domain.models import OrderBookSnapshot


def _to_float(value: object, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PolymarketParseError(f"Invalid numeric field: {field_name}") from exc


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise PolymarketParseError("Missing orderbook timestamp")
    if value.isdigit():
        raw = int(value)
        if raw >= 10**18:
            raw = raw / 1_000_000_000
        elif raw >= 10**15:
            raw = raw / 1_000_000
        elif raw >= 10**12:
            raw = raw / 1_000
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class ClobMarketDataClient:
    base_url: str = "https://clob.polymarket.com"
    timeout_seconds: float = 5.0
    http_client: httpx.Client = field(default_factory=httpx.Client)

    def get_orderbook(self, asset_id: str) -> dict[str, object]:
        payload = self._get_json("/book", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected orderbook response shape")
        return payload

    def get_midpoint(self, asset_id: str) -> dict[str, object]:
        payload = self._get_json("/midpoint", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected midpoint response shape")
        return payload

    def get_price(self, asset_id: str) -> dict[str, object]:
        payload = self._get_json("/price", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected price response shape")
        return payload

    def probe(self) -> dict[str, object]:
        try:
            response = self.http_client.get(self.base_url, timeout=self.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise PolymarketTransportError(f"Timeout fetching {self.base_url}") from exc
        except httpx.HTTPError as exc:
            raise PolymarketTransportError(f"Transport error fetching {self.base_url}") from exc
        if response.status_code >= 500:
            raise PolymarketHTTPError(f"HTTP error fetching {self.base_url}: {response.status_code}")
        return {"status": "ok", "status_code": response.status_code}

    def close(self) -> None:
        self.http_client.close()

    def _get_json(self, path: str, params: dict[str, object] | None = None) -> object:
        url = f"{self.base_url}{path}"
        try:
            response = self.http_client.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PolymarketTransportError(f"Timeout fetching {url}") from exc
        except httpx.HTTPStatusError as exc:
            raise PolymarketHTTPError(f"HTTP error fetching {url}: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise PolymarketTransportError(f"Transport error fetching {url}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise PolymarketParseError(f"Invalid JSON from {url}") from exc


class PolymarketOrderBookAdapter:
    def __init__(self, client: ClobMarketDataClient) -> None:
        self.client = client

    def get_orderbook(self, asset_id: str, market_id: str | None = None) -> ClobOrderBook:
        payload = self.client.get_orderbook(asset_id)
        try:
            bids = payload.get("bids", [])
            asks = payload.get("asks", [])
            best_bid = self._best_price(bids, choose_max=True)
            best_ask = self._best_price(asks, choose_max=False)
            timestamp = _parse_datetime(str(payload.get("timestamp") or payload.get("ts") or payload.get("hashTimestamp")))

            midpoint_payload = self.client.get_midpoint(asset_id)
            midpoint = _to_float(
                midpoint_payload.get("midpoint", midpoint_payload.get("price", midpoint_payload.get("mid"))),
                "midpoint",
            )
            spread_pct = 0.0 if midpoint == 0 else round((best_ask - best_bid) / midpoint, 6)

            reference_price = None
            pricing_metadata: dict[str, object] = {
                "authoritative_current_price": "midpoint",
                "orderbook_source": "/book",
                "midpoint_source": "/midpoint",
                "reference_price_source": "/price",
                "price_status": "available",
                "warnings": [],
            }
            try:
                price_payload = self.client.get_price(asset_id)
                reference_price = _to_float(
                    price_payload.get("price", price_payload.get("last", price_payload.get("reference_price"))),
                    "price",
                )
            except PolymarketAdapterError as exc:
                pricing_metadata["price_status"] = "unavailable"
                pricing_metadata["warnings"] = [f"price_fetch_failed:{exc.__class__.__name__}"]

            return ClobOrderBook(
                asset_id=asset_id,
                snapshot=OrderBookSnapshot(
                    market_id=market_id or asset_id,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    midpoint=midpoint,
                    spread_pct=spread_pct,
                    timestamp=timestamp,
                ),
                reference_price=reference_price,
                pricing_metadata=pricing_metadata,
                raw_payload=payload,
            )
        except (TypeError, ValueError, KeyError, PolymarketParseError) as exc:
            raise PolymarketParseError(f"Invalid order book payload for {asset_id}") from exc

    def get_snapshot(self, market_id: str) -> OrderBookSnapshot:
        return self.get_orderbook(market_id, market_id=market_id).snapshot

    def _best_price(self, levels: object, choose_max: bool) -> float:
        if not isinstance(levels, list) or not levels:
            raise PolymarketParseError("Order book levels are missing")
        prices: list[float] = []
        for level in levels:
            if isinstance(level, dict):
                price = level.get("price")
            elif isinstance(level, list) and level:
                price = level[0]
            else:
                raise PolymarketParseError("Unsupported order book level shape")
            prices.append(_to_float(price, "price"))
        return max(prices) if choose_max else min(prices)


class PolymarketClient(ClobMarketDataClient):
    pass
