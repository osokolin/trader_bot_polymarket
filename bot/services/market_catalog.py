from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.adapters.polymarket.errors import PolymarketParseError
from bot.adapters.polymarket.gamma_client import GammaApiClient
from bot.adapters.polymarket.models import GammaEventSummary, GammaMarketSummary


_CATEGORY_LABELS = {
    "ai": "AI",
    "business": "Business",
    "crypto": "Crypto",
    "culture": "Culture",
    "economics": "Economics",
    "finance": "Finance",
    "macro": "Macro",
    "politics": "Politics",
    "science": "Science",
    "sports": "Sports",
    "technology": "Technology",
    "world": "World",
}


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


def _display_category(value: str) -> str:
    normalized = _normalize_category(value)
    if normalized == "unknown":
        return "unknown"
    return _CATEGORY_LABELS.get(normalized, normalized.title())


def _first_present(payload: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload.get(key)
    return None


@dataclass(slots=True)
class MarketCatalogOutcome:
    label: str
    token_id: str | None
    best_bid: float | None = None
    best_ask: float | None = None
    midpoint: float | None = None
    implied_probability: float | None = None


@dataclass(slots=True)
class MarketCatalogDetail:
    market: GammaMarketSummary
    description_text: str
    rules_text: str
    important_notes: list[str]
    event_slug: str | None
    related_markets: list[GammaMarketSummary]
    outcomes: list[MarketCatalogOutcome]
    polymarket_url: str | None
    gamma_url: str


@dataclass(slots=True)
class MarketCatalogBrowseQuery:
    scope: str = "active"
    categories: list[str] = field(default_factory=list)
    search: str = ""
    min_liquidity: float | None = None
    orderbook_only: bool = False
    sort: str = "liquidity_desc"
    page: int = 1
    page_size: int = 20


@dataclass(slots=True)
class MarketCatalogBrowseResult:
    items: list[GammaMarketSummary]
    available_categories: list[str]
    applied_query: MarketCatalogBrowseQuery
    total_count: int
    supported_sorts: tuple[str, ...] = ("liquidity_desc", "volume_desc", "ending_soon", "newest")

    @property
    def total_pages(self) -> int:
        if self.applied_query.page_size <= 0:
            return 1
        return max(1, (self.total_count + self.applied_query.page_size - 1) // self.applied_query.page_size)


@dataclass(slots=True)
class MarketCatalogService:
    gamma_client: GammaApiClient

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[GammaMarketSummary]:
        payloads = self.gamma_client.list_markets(limit=limit, active=active, closed=closed)
        return self._map_market_payloads(payloads)

    def get_market_detail(self, slug_or_market_id: str) -> MarketCatalogDetail:
        payload = self._get_market_payload(slug_or_market_id)
        market = self._map_market_payloads([payload])[0]
        description_text = str(_first_present(payload, "description", "rules", "rulesText") or "")
        rules_text = str(_first_present(payload, "resolutionSource", "resolution_criteria", "resolutionCriteria", "notes") or "")
        important_notes = [
            str(value)
            for value in [
                _first_present(payload, "notes"),
                _first_present(payload, "comment"),
                _first_present(payload, "resolutionSource"),
            ]
            if value not in (None, "", description_text, rules_text)
        ]
        outcomes = self._extract_outcomes(payload)
        event_slug, related_markets = self._related_markets(payload, market.market_id)
        polymarket_url = self._polymarket_url(payload, event_slug)
        gamma_url = f"{self.gamma_client.base_url}/markets?slug={market.slug or market.market_id}"
        return MarketCatalogDetail(
            market=market,
            description_text=description_text,
            rules_text=rules_text,
            important_notes=important_notes,
            event_slug=event_slug,
            related_markets=related_markets[:5],
            outcomes=outcomes,
            polymarket_url=polymarket_url,
            gamma_url=gamma_url,
        )

    def browse_markets(self, query: MarketCatalogBrowseQuery) -> MarketCatalogBrowseResult:
        batch_limit = max(query.page_size * 6, 120)
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
        total_count = len(filtered_items)
        start = max(0, (query.page - 1) * query.page_size)
        end = start + query.page_size
        return MarketCatalogBrowseResult(
            items=filtered_items[start:end],
            available_categories=available_categories,
            applied_query=query,
            total_count=total_count,
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

    def _get_market_payload(self, slug_or_market_id: str) -> dict[str, object]:
        try:
            return self.gamma_client.get_market_by_slug(slug_or_market_id)
        except PolymarketParseError:
            return self.gamma_client.get_market(slug_or_market_id)

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
                    category=self._resolve_category(payload, event_payload),
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

    def _extract_outcomes(self, payload: dict[str, object]) -> list[MarketCatalogOutcome]:
        outcomes: list[MarketCatalogOutcome] = []
        tokens = payload.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                label = str(_first_present(token, "outcome", "title", "name") or "Outcome")
                token_id = _first_present(token, "token_id", "asset_id", "clobTokenId")
                outcomes.append(
                    MarketCatalogOutcome(
                        label=label,
                        token_id=None if token_id is None else str(token_id),
                    )
                )
        raw_outcomes = payload.get("outcomes")
        if isinstance(raw_outcomes, str):
            stripped = raw_outcomes.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                except ValueError:
                    parsed = []
                if isinstance(parsed, list):
                    for value in parsed:
                        label = str(value)
                        if not any(existing.label == label for existing in outcomes):
                            outcomes.append(MarketCatalogOutcome(label=label, token_id=None))
        elif isinstance(raw_outcomes, list):
            for value in raw_outcomes:
                label = str(value)
                if not any(existing.label == label for existing in outcomes):
                    outcomes.append(MarketCatalogOutcome(label=label, token_id=None))
        return outcomes or [MarketCatalogOutcome(label="Outcome", token_id=None)]

    def _resolve_category(self, payload: dict[str, object], event_payload: object) -> str:
        candidates: list[str] = []
        for key in ("category", "series", "groupItemTitle", "groupTitle"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value)
        if isinstance(event_payload, dict):
            for key in ("category", "series", "groupItemTitle", "groupTitle"):
                value = event_payload.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value)
            candidates.extend(self._extract_tag_candidates(event_payload.get("tags")))
        candidates.extend(self._extract_tag_candidates(payload.get("tags")))

        for value in candidates:
            display = _display_category(value)
            if display != "unknown":
                return display
        return "unknown"

    def _extract_tag_candidates(self, raw_tags: object) -> list[str]:
        if not isinstance(raw_tags, list):
            return []
        values: list[str] = []
        for tag in raw_tags:
            if isinstance(tag, str) and tag.strip():
                values.append(tag)
                continue
            if isinstance(tag, dict):
                for key in ("label", "name", "title", "slug"):
                    value = tag.get(key)
                    if isinstance(value, str) and value.strip():
                        values.append(value)
                        break
        return values

    def _related_markets(self, payload: dict[str, object], current_market_id: str) -> tuple[str | None, list[GammaMarketSummary]]:
        event_payload = payload.get("event")
        if isinstance(event_payload, dict):
            event_slug = None if event_payload.get("slug") is None else str(event_payload.get("slug"))
            markets = event_payload.get("markets")
            if isinstance(markets, list):
                related = [item for item in self._map_market_payloads([market for market in markets if isinstance(market, dict)]) if item.market_id != current_market_id]
                return event_slug, related
        event_id = payload.get("eventId")
        if event_id is None:
            return None, []
        event = self.gamma_client.get_event(str(event_id))
        event_slug = None if event.get("slug") is None else str(event.get("slug"))
        markets = event.get("markets")
        if not isinstance(markets, list):
            return event_slug, []
        related = [item for item in self._map_market_payloads([market for market in markets if isinstance(market, dict)]) if item.market_id != current_market_id]
        return event_slug, related

    def _polymarket_url(self, payload: dict[str, object], event_slug: str | None) -> str | None:
        direct = _first_present(payload, "url", "marketUrl")
        if direct is not None:
            return str(direct)
        if event_slug:
            return f"https://polymarket.com/event/{event_slug}"
        slug = payload.get("slug")
        if slug is not None:
            return f"https://polymarket.com/event/{slug}"
        return None

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
