from __future__ import annotations

import unittest

from bot.services.market_catalog import MarketCatalogBrowseQuery, MarketCatalogService


class _FakeGammaClient:
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
        ]
        filtered = [
            item
            for item in items
            if item["active"] is active and item["closed"] is closed
        ]
        return filtered[:limit]


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
                limit=10,
            )
        )
        self.assertEqual([item.market_id for item in result.items], ["mkt_politics"])
        self.assertEqual(result.available_categories, ["crypto", "Politics", "sports"])

    def test_browse_markets_sorts_by_liquidity_desc_by_default(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="active", limit=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_crypto", "mkt_politics"])

    def test_browse_markets_sorts_by_ending_soon(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="all", sort="ending_soon", limit=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_sports", "mkt_politics", "mkt_crypto"])

    def test_browse_markets_can_filter_closed_only(self) -> None:
        result = self.service.browse_markets(MarketCatalogBrowseQuery(scope="closed", limit=10))
        self.assertEqual([item.market_id for item in result.items], ["mkt_sports"])


if __name__ == "__main__":
    unittest.main()
