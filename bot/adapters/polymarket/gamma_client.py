from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from bot.adapters.polymarket.errors import PolymarketHTTPError, PolymarketParseError, PolymarketTransportError
from bot.adapters.polymarket.models import GammaMarketMetadata
from bot.domain.models import Market


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

    def get_market(self, market_id: str) -> dict[str, object]:
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

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[dict[str, object]]:
        payload = self._get_json(
            "/markets",
            params={"limit": limit, "active": str(active).lower(), "closed": str(closed).lower()},
        )
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise PolymarketParseError("Unexpected Gamma markets response shape")
        return payload

    def get_event(self, event_id: str) -> dict[str, object]:
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

    def list_events(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[dict[str, object]]:
        payload = self._get_json(
            "/events",
            params={"limit": limit, "active": str(active).lower(), "closed": str(closed).lower()},
        )
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise PolymarketParseError("Unexpected Gamma events response shape")
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


class PolymarketMarketMetadataAdapter:
    def __init__(self, client: GammaApiClient) -> None:
        self.client = client

    def get_market_metadata(self, market_id: str) -> GammaMarketMetadata:
        payload = self.client.get_market(market_id)
        try:
            liquidity_usd = _to_float(payload, "liquidityClob", "liquidity", default=0.0) or 0.0
            spread_pct = _to_float(payload, "spread", "spreadPct", default=0.0) or 0.0
            resolution_value = _first_present(payload, "endDate", "end_date_iso", "endDateIso")
            market = Market(
                market_id=str(_first_present(payload, "id", "market_id")),
                title=str(_first_present(payload, "question", "title")),
                category=str(_first_present(payload, "category") or "unknown"),
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
                last_traded_price=_to_float(payload, "lastTradePrice", "last_trade_price", default=None),
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
