from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from bot.domain.models import Market


class PolymarketAdapterError(RuntimeError):
    pass


class PolymarketTransportError(PolymarketAdapterError):
    pass


class PolymarketHTTPError(PolymarketAdapterError):
    pass


class PolymarketParseError(PolymarketAdapterError):
    pass


def _parse_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class PolymarketClient:
    base_url: str = "https://clob.polymarket.com"
    timeout_seconds: float = 5.0
    http_client: httpx.Client = field(default_factory=httpx.Client)

    def get_market(self, market_id: str) -> dict:
        return self._get_json(f"/markets/{market_id}")

    def get_orderbook(self, market_id: str) -> dict:
        return self._get_json(f"/markets/{market_id}/orderbook")

    def close(self) -> None:
        self.http_client.close()

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self.http_client.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PolymarketTransportError(f"Timeout fetching {url}") from exc
        except httpx.HTTPStatusError as exc:
            raise PolymarketHTTPError(f"HTTP error fetching {url}: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise PolymarketTransportError(f"Transport error fetching {url}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PolymarketParseError(f"Invalid JSON from {url}") from exc
        if not isinstance(payload, dict):
            raise PolymarketParseError(f"Unexpected response shape from {url}")
        return payload


class PolymarketMarketMetadataAdapter:
    def __init__(self, client: PolymarketClient) -> None:
        self.client = client

    def get_market(self, market_id: str) -> Market:
        payload = self.client.get_market(market_id)
        try:
            return Market(
                market_id=str(payload["id"]),
                title=payload["question"],
                category=payload.get("category", "unknown"),
                liquidity_usd=float(payload.get("liquidity", 0.0)),
                spread_pct=float(payload.get("spread", 0.0)),
                resolution_time=_parse_datetime(payload["end_date_iso"]),
                rules_text=payload.get("description", ""),
                rules_confidence=float(payload.get("rules_confidence", 1.0)),
                tags=list(payload.get("tags", [])),
                has_orderbook=bool(payload.get("enable_order_book", True)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PolymarketParseError(f"Invalid market payload for {market_id}") from exc
