from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

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


def _optional_datetime(payload: dict[str, object], *keys: str) -> datetime | None:
    value: object | None = None
    for key in keys:
        if payload.get(key) not in (None, ""):
            value = payload.get(key)
            break
    if value is None:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PolymarketParseError(f"Invalid Gamma catalog datetime field: {keys[0]}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalize_category(value: str) -> str:
    normalized = " ".join(value.replace("_", " ").replace("-", " ").split()).strip().lower()
    return normalized or "unknown"


@dataclass(slots=True)
class MarketCatalogBrowseQuery:
    scope: str = "active"
    categories: list[str] = field(default_factory=list)
    search: str = ""
    min_liquidity: float | None = None
    orderbook_only: bool = False
    sort: str = "liquidity_desc"
    limit: int = 20


@dataclass(slots=True)
class MarketCatalogBrowseResult:
    items: list[GammaMarketSummary]
    available_categories: list[str]
    applied_query: MarketCatalogBrowseQuery
    supported_sorts: tuple[str, ...] = ("liquidity_desc", "volume_desc", "ending_soon", "newest")


@dataclass(slots=True)
class MarketCatalogService:
    gamma_client: GammaApiClient

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[GammaMarketSummary]:
        payloads = self.gamma_client.list_markets(limit=limit, active=active, closed=closed)
        return self._map_market_payloads(payloads)

    def browse_markets(self, query: MarketCatalogBrowseQuery) -> MarketCatalogBrowseResult:
        batch_limit = max(query.limit * 6, 120)
        if query.scope == "all":
            payloads = self.gamma_client.list_markets(limit=batch_limit, active=True, closed=False)
            payloads.extend(self.gamma_client.list_markets(limit=batch_limit, active=False, closed=True))
        elif query.scope == "closed":
            payloads = self.gamma_client.list_markets(limit=batch_limit, active=False, closed=True)
        else:
            payloads = self.gamma_client.list_markets(limit=batch_limit, active=True, closed=False)

        unique_items: list[GammaMarketSummary] = []
        seen_market_ids: set[str] = set()
        for item in self._map_market_payloads(payloads):
            if item.market_id in seen_market_ids:
                continue
            seen_market_ids.add(item.market_id)
            unique_items.append(item)

        available_categories = sorted({item.category for item in unique_items}, key=str.lower)
        normalized_categories = {_normalize_category(value) for value in query.categories}
        search_text = query.search.strip().lower()

        filtered_items: list[GammaMarketSummary] = []
        for item in unique_items:
            if normalized_categories and _normalize_category(item.category) not in normalized_categories:
                continue
            if query.min_liquidity is not None and (item.liquidity_usd or 0.0) < query.min_liquidity:
                continue
            if query.orderbook_only and not item.enable_order_book:
                continue
            if search_text:
                haystack = " ".join(
                    filter(
                        None,
                        [
                            item.question.lower(),
                            (item.slug or "").lower(),
                            (item.event_title or "").lower(),
                            item.market_id.lower(),
                        ],
                    )
                )
                if search_text not in haystack:
                    continue
            filtered_items.append(item)

        filtered_items.sort(key=self._sort_key(query.sort), reverse=self._reverse_sort(query.sort))
        return MarketCatalogBrowseResult(
            items=filtered_items[: query.limit],
            available_categories=available_categories,
            applied_query=query,
        )

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

    def _map_market_payloads(self, payloads: list[dict[str, object]]) -> list[GammaMarketSummary]:
        items: list[GammaMarketSummary] = []
        for payload in payloads:
            event_payload = payload.get("event")
            items.append(
                GammaMarketSummary(
                    market_id=str(payload.get("id")),
                    question=str(payload.get("question") or payload.get("title") or "Untitled market"),
                    event_id=None if payload.get("eventId") is None else str(payload.get("eventId")),
                    event_title=str(event_payload.get("title")) if isinstance(event_payload, dict) and event_payload.get("title") else (
                        None if payload.get("eventTitle") is None else str(payload.get("eventTitle"))
                    ),
                    slug=None if payload.get("slug") is None else str(payload.get("slug")),
                    category=str(payload.get("category") or "unknown"),
                    active=bool(payload.get("active", True)),
                    closed=bool(payload.get("closed", False)),
                    archived=bool(payload.get("archived", False)),
                    enable_order_book=bool(payload.get("enableOrderBook", True)),
                    liquidity_usd=_optional_float(payload, "liquidityClob"),
                    volume_usd=_optional_float(payload, "volumeClob"),
                    end_time=_optional_datetime(payload, "endDate", "end_date_iso", "endDateIso"),
                    created_at=_optional_datetime(payload, "createdAt", "created_at", "createdTime"),
                )
            )
        return items

    def _sort_key(self, sort: str):
        max_dt = datetime.max.replace(tzinfo=timezone.utc)
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        if sort == "volume_desc":
            return lambda item: (item.volume_usd or 0.0, item.liquidity_usd or 0.0, item.question.lower())
        if sort == "ending_soon":
            return lambda item: (item.end_time or max_dt, -(item.liquidity_usd or 0.0), item.question.lower())
        if sort == "newest":
            return lambda item: (item.created_at or min_dt, item.question.lower())
        return lambda item: (item.liquidity_usd or 0.0, item.volume_usd or 0.0, item.question.lower())

    def _reverse_sort(self, sort: str) -> bool:
        return sort in {"liquidity_desc", "volume_desc", "newest"}
