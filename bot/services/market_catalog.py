from __future__ import annotations

from dataclasses import dataclass

from bot.adapters.polymarket.errors import PolymarketParseError
from bot.adapters.polymarket.gamma_client import GammaApiClient
from bot.adapters.polymarket.models import GammaEventSummary, GammaMarketSummary


def _optional_float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PolymarketParseError(f"Invalid Gamma catalog numeric field: {key}") from exc


@dataclass(slots=True)
class MarketCatalogService:
    gamma_client: GammaApiClient

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[GammaMarketSummary]:
        payloads = self.gamma_client.list_markets(limit=limit, active=active, closed=closed)
        items: list[GammaMarketSummary] = []
        for payload in payloads:
            items.append(
                GammaMarketSummary(
                    market_id=str(payload.get("id")),
                    question=str(payload.get("question") or payload.get("title") or "Untitled market"),
                    event_id=None if payload.get("eventId") is None else str(payload.get("eventId")),
                    slug=None if payload.get("slug") is None else str(payload.get("slug")),
                    category=str(payload.get("category") or "unknown"),
                    active=bool(payload.get("active", True)),
                    closed=bool(payload.get("closed", False)),
                    archived=bool(payload.get("archived", False)),
                    enable_order_book=bool(payload.get("enableOrderBook", True)),
                    liquidity_usd=_optional_float(payload, "liquidityClob"),
                    volume_usd=_optional_float(payload, "volumeClob"),
                )
            )
        return items

    def list_events(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[GammaEventSummary]:
        payloads = self.gamma_client.list_events(limit=limit, active=active, closed=closed)
        items: list[GammaEventSummary] = []
        for payload in payloads:
            markets = payload.get("markets")
            items.append(
                GammaEventSummary(
                    event_id=str(payload.get("id")),
                    title=str(payload.get("title") or payload.get("ticker") or "Untitled event"),
                    slug=None if payload.get("slug") is None else str(payload.get("slug")),
                    active=bool(payload.get("active", True)),
                    closed=bool(payload.get("closed", False)),
                    archived=bool(payload.get("archived", False)),
                    market_count=len(markets) if isinstance(markets, list) else 0,
                )
            )
        return items
