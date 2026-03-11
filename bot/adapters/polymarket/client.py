from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from bot.adapters.polymarket.models import ClobOrderBook, GammaMarketMetadata
from bot.domain.models import Market, OrderBookSnapshot


class PolymarketAdapterError(RuntimeError):
    pass


class PolymarketTransportError(PolymarketAdapterError):
    pass


class PolymarketHTTPError(PolymarketAdapterError):
    pass


class PolymarketParseError(PolymarketAdapterError):
    pass


class PolymarketStaleDataError(PolymarketAdapterError):
    pass


class PolymarketWebSocketError(PolymarketAdapterError):
    pass


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise PolymarketParseError("Missing datetime value")
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first_present(payload: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _to_float(payload: dict[str, object], *keys: str, default: float | None = None) -> float | None:
    value = _first_present(payload, *keys)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PolymarketParseError(f"Invalid numeric field for keys={keys}") from exc


def _parse_asset_id(payload: dict[str, object]) -> str:
    direct = _first_present(payload, "asset_id", "clobTokenId", "clob_token_id")
    if direct is not None:
        return str(direct)
    token_ids = _first_present(payload, "clobTokenIds", "clob_token_ids")
    if isinstance(token_ids, str):
        stripped = token_ids.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            import json

            parsed = json.loads(stripped)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0])
        if stripped:
            return stripped
    tokens = _first_present(payload, "tokens")
    if isinstance(tokens, list) and tokens:
        first = tokens[0]
        if isinstance(first, dict):
            token_id = _first_present(first, "token_id", "asset_id", "clobTokenId")
            if token_id is not None:
                return str(token_id)
    raise PolymarketParseError("Could not determine asset_id for market payload")


@dataclass(slots=True)
class GammaApiClient:
    base_url: str = "https://gamma-api.polymarket.com"
    timeout_seconds: float = 5.0
    http_client: httpx.Client = field(default_factory=httpx.Client)

    def get_market(self, market_id: str) -> dict:
        payload = self._get_json("/markets", params={"id": market_id})
        if isinstance(payload, list):
            if not payload:
                raise PolymarketParseError(f"No Gamma market payload returned for {market_id}")
            first = payload[0]
            if not isinstance(first, dict):
                raise PolymarketParseError("Unexpected Gamma market list item shape")
            return first
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected Gamma market response shape")
        return payload

    def get_event(self, event_id: str) -> dict:
        payload = self._get_json("/events", params={"id": event_id})
        if isinstance(payload, list):
            if not payload:
                raise PolymarketParseError(f"No Gamma event payload returned for {event_id}")
            first = payload[0]
            if not isinstance(first, dict):
                raise PolymarketParseError("Unexpected Gamma event list item shape")
            return first
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected Gamma event response shape")
        return payload

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


@dataclass(slots=True)
class ClobMarketDataClient:
    base_url: str = "https://clob.polymarket.com"
    timeout_seconds: float = 5.0
    http_client: httpx.Client = field(default_factory=httpx.Client)

    def get_orderbook(self, asset_id: str) -> dict:
        payload = self._get_json("/book", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected orderbook response shape")
        return payload

    def get_midpoint(self, asset_id: str) -> dict:
        payload = self._get_json("/midpoint", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected midpoint response shape")
        return payload

    def get_last_trade_price(self, asset_id: str) -> dict:
        payload = self._get_json("/last-trade-price", params={"token_id": asset_id})
        if not isinstance(payload, dict):
            raise PolymarketParseError("Unexpected last-trade-price response shape")
        return payload

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


class PolymarketClient(ClobMarketDataClient):
    pass


class PolymarketMarketMetadataAdapter:
    def __init__(self, client: GammaApiClient) -> None:
        self.client = client

    def get_market_metadata(self, market_id: str) -> GammaMarketMetadata:
        payload = self.client.get_market(market_id)
        try:
            liquidity_usd = _to_float(payload, "liquidityClob", "liquidity", default=0.0) or 0.0
            spread_pct = _to_float(payload, "spread", "spreadPct", default=0.0) or 0.0
            last_traded_price = _to_float(payload, "lastTradePrice", "last_trade_price", default=None)
            resolution_value = _first_present(payload, "endDate", "end_date_iso", "endDateIso")
            market = Market(
                market_id=str(_first_present(payload, "id", "market_id")),
                title=str(_first_present(payload, "question", "title")),
                category=str(_first_present(payload, "category", default := "unknown") or "unknown"),
                liquidity_usd=liquidity_usd,
                spread_pct=spread_pct,
                resolution_time=_parse_datetime(str(resolution_value)),
                rules_text=str(_first_present(payload, "description", "rules", "rulesText") or ""),
                rules_confidence=float(_to_float(payload, "rules_confidence", "rulesConfidence", default=1.0) or 1.0),
                tags=[str(item) for item in payload.get("tags", [])] if isinstance(payload.get("tags", []), list) else [],
                has_orderbook=bool(_first_present(payload, "enableOrderBook", "enable_order_book", "hasOrderBook") is not False),
                event_id=None if _first_present(payload, "event_id", "eventId") is None else str(_first_present(payload, "event_id", "eventId")),
                outcome_token_id=_parse_asset_id(payload),
                active=bool(payload.get("active", True)),
                closed=bool(payload.get("closed", False)),
                archived=bool(payload.get("archived", False)),
                last_traded_price=last_traded_price,
            )
        except (TypeError, ValueError, KeyError, PolymarketParseError) as exc:
            raise PolymarketParseError(f"Invalid Gamma market payload for {market_id}") from exc
        return GammaMarketMetadata(
            market=market,
            asset_id=market.outcome_token_id or _parse_asset_id(payload),
            raw_payload=payload,
        )

    def get_market(self, market_id: str) -> Market:
        return self.get_market_metadata(market_id).market


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
            midpoint = round((best_bid + best_ask) / 2, 4)
            spread_pct = 0.0 if midpoint == 0 else round((best_ask - best_bid) / midpoint, 6)
            timestamp = _parse_datetime(str(_first_present(payload, "timestamp", "ts", "hashTimestamp")))
            last_trade_price = None
            try:
                last_trade_payload = self.client.get_last_trade_price(asset_id)
                last_trade_price = _to_float(last_trade_payload, "price", "last_trade_price", default=None)
            except PolymarketAdapterError:
                last_trade_price = None
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
                last_trade_price=last_trade_price,
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
                price = _first_present(level, "price")
            elif isinstance(level, list) and level:
                price = level[0]
            else:
                raise PolymarketParseError("Unsupported order book level shape")
            prices.append(float(price))
        return max(prices) if choose_max else min(prices)
