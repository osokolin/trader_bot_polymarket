from __future__ import annotations

import unittest

from bot.adapters.polymarket.errors import PolymarketParseError
from bot.services.market_catalog import MarketCatalogBrowseQuery, MarketCatalogService


class _FakeGammaClient:
    base_url = "https://gamma-api.polymarket.com"

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[dict[str, object]]:
        items = [
            {
                "id": "mkt_crypto",
                "question": "Will BTC hit 120k?",
                "eventId": "evt_crypto",
                "eventTitle": "Crypto Markets",
                "slug": "btc-hit-120k",
                "category": "crypto",
                "active": True,
                "closed": False,
                "archived": False,
                "enableOrderBook": True,
                "liquidityClob": 15000,
                "volumeClob": 45000,
                "endDate": "2026-03-20T00:00:00Z",
                "createdAt": "2026-03-01T00:00:00Z",
            },
            {
                "id": "mkt_politics",
                "question": "Will turnout exceed 60 percent?",
                "eventId": "evt_politics",
                "eventTitle": "Election Tracker",
                "slug": "turnout-above-60",
                "category": "Politics",
                "active": True,
                "closed": False,
                "archived": False,
                "enableOrderBook": True,
                "liquidityClob": 5000,
                "volumeClob": 9000,
                "endDate": "2026-03-15T00:00:00Z",
                "createdAt": "2026-03-10T00:00:00Z",
            },
            {
                "id": "mkt_sports",
                "question": "Will Team A win the final?",
                "eventId": "evt_sports",
                "eventTitle": "Sports Finals",
                "slug": "team-a-win-final",
                "category": "sports",
                "active": False,
                "closed": True,
                "archived": False,
                "enableOrderBook": False,
                "liquidityClob": 800,
                "volumeClob": 1200,
                "endDate": "2026-03-14T00:00:00Z",
                "createdAt": "2026-03-12T00:00:00Z",
            },
            {
                "id": "mkt_macro",
                "question": "Will CPI cool next month?",
                "eventId": "evt_macro",
                "eventTitle": "Macro Signals",
                "slug": "cpi-cools-next-month",
                "category": "",
                "event": {"category": "macro"},
                "active": True,
                "closed": False,
                "archived": False,
                "enableOrderBook": True,
                "liquidityClob": 2500,
                "volumeClob": 3300,
                "endDate": "2026-03-18T00:00:00Z",
                "createdAt": "2026-03-11T00:00:00Z",
            },
        ]
        filtered = [
            item
            for item in items
            if item["active"] is active and item["closed"] is closed
        ]
        return filtered[:limit]

    def get_market_by_slug(self, slug: str) -> dict[str, object]:
        for payload in self.list_markets(limit=20, active=True, closed=False) + self.list_markets(limit=20, active=False, closed=True):
            if payload.get("slug") == slug:
                return {
                    **payload,
                    "description": "Resolution follows the official settlement report.",
                    "resolutionSource": "Official release wins.",
                    "tokens": [
                        {"outcome": "YES", "clobTokenId": "asset_yes"},
                        {"outcome": "NO", "clobTokenId": "asset_no"},
                    ],
                    "event": {
                        "slug": "crypto-markets",
                        "title": "Crypto Markets",
                        "markets": [
                            payload,
                            {
                                "id": "mkt_related",
                                "question": "Will ETH hit 8k?",
                                "eventId": "evt_crypto",
                                "eventTitle": "Crypto Markets",
                                "slug": "eth-hit-8k",
                                "category": "crypto",
                                "active": True,
                                "closed": False,
                                "archived": False,
                                "enableOrderBook": True,
                                "liquidityClob": 7000,
                                "volumeClob": 14000,
                            },
                        ],
                    },
                }
        raise PolymarketParseError(f"unexpected slug: {slug}")

    def get_market(self, market_id: str) -> dict[str, object]:
        for payload in self.list_markets(limit=20, active=True, closed=False) + self.list_markets(limit=20, active=False, closed=True):
            if payload.get("id") == market_id:
                return payload
        raise AssertionError(f"unexpected market_id: {market_id}")

    def get_event(self, event_id: str) -> dict[str, object]:
        return {"id": event_id, "slug": "crypto-markets", "title": "Crypto Markets", "markets": []}


class MarketCatalogServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MarketCatalogService(_FakeGammaClient())  # type: ignore[arg-type]

    def test_browse_markets_filters_categories_search_and_liquidity(self) -> None:
        result = self.service.browse_markets(
            MarketCatalogBrowseQuery(
                scope="all",
                categories=["politics"],
                search="turnout",
                min_liquidity=1000,
                orderbook_only=True,
                sort="volume_desc",
                page_size=10,
            )
        )
        self.assertEqual([item.market_id for item in result.items], ["mkt_politics"])
        self.assertEqual(result.available_categories, ["Crypto", "Macro", "Politics", "Sports"])

    def test_browse_markets_sorts_by_liquidity_desc_by_default(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="active", page_size=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_crypto", "mkt_politics", "mkt_macro"])

    def test_browse_markets_sorts_by_ending_soon(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="all", sort="ending_soon", page_size=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_sports", "mkt_politics", "mkt_macro", "mkt_crypto"])

    def test_browse_markets_can_filter_closed_only(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="closed", page_size=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_sports"])

    def test_browse_markets_resolves_missing_category_from_event_metadata(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="active", categories=["macro"], page_size=20))
        self.assertEqual([item.market_id for item in result.items], ["mkt_macro"])

    def test_browse_markets_paginates_after_sorting(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="active", page=2, page_size=1))
        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.total_pages, 3)
        self.assertEqual([item.market_id for item in result.items], ["mkt_politics"])

    def test_get_market_detail_includes_rules_outcomes_and_related_markets(self) -> None:
        detail = self.service.get_market_detail("btc-hit-120k")
        self.assertEqual(detail.market.market_id, "mkt_crypto")
        self.assertEqual(detail.description_text, "Resolution follows the official settlement report.")
        self.assertEqual(detail.rules_text, "Official release wins.")
        self.assertEqual([outcome.label for outcome in detail.outcomes], ["YES", "NO"])
        self.assertEqual([item.market_id for item in detail.related_markets], ["mkt_related"])
        self.assertEqual(detail.polymarket_url, "https://polymarket.com/event/crypto-markets")

    def test_get_market_detail_handles_missing_rules_fields(self) -> None:
        detail = self.service.get_market_detail("mkt_politics")
        self.assertEqual(detail.market.market_id, "mkt_politics")
        self.assertEqual(detail.description_text, "")
        self.assertEqual(detail.rules_text, "")
        self.assertEqual(detail.related_markets, [])


if __name__ == "__main__":
    unittest.main()
