from __future__ import annotations

import json
import unittest

import httpx

from bot.adapters.polymarket.client import (
    PolymarketClient,
    PolymarketHTTPError,
    PolymarketMarketMetadataAdapter,
    PolymarketParseError,
    PolymarketTransportError,
)
from bot.adapters.polymarket.market_stream import PolymarketOrderBookAdapter
from bot.adapters.polymarket.models import OrderRequest
from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter


class PolymarketAdaptersTest(unittest.TestCase):
    def _mock_client(self, handler) -> PolymarketClient:
        return PolymarketClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_market_metadata_adapter_maps_market(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = {
                "id": "mkt_1",
                "question": "Will BTC close above 100k?",
                "category": "crypto",
                "liquidity": 15000,
                "spread": 0.02,
                "end_date_iso": "2026-04-01T00:00:00Z",
                "description": "Clear resolution rules",
                "rules_confidence": 0.95,
                "tags": ["crypto"],
                "enable_order_book": True,
            }
            return httpx.Response(200, json=payload)

        client = self._mock_client(handler)
        adapter = PolymarketMarketMetadataAdapter(client)
        market = adapter.get_market("mkt_1")
        self.assertEqual(market.market_id, "mkt_1")
        self.assertEqual(market.category, "crypto")
        self.assertTrue(market.has_orderbook)
        client.close()

    def test_orderbook_adapter_maps_snapshot(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"best_bid": 0.48, "best_ask": 0.52, "timestamp": "2026-03-11T09:00:00Z"},
            )

        client = self._mock_client(handler)
        adapter = PolymarketOrderBookAdapter(client)
        snapshot = adapter.get_snapshot("mkt_1")
        self.assertEqual(snapshot.midpoint, 0.5)
        self.assertGreater(snapshot.spread_pct, 0)
        client.close()

    def test_client_raises_transport_error_on_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        client = self._mock_client(handler)
        with self.assertRaises(PolymarketTransportError):
            client.get_market("mkt_1")
        client.close()

    def test_client_raises_http_error_on_bad_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        client = self._mock_client(handler)
        with self.assertRaises(PolymarketHTTPError):
            client.get_market("mkt_1")
        client.close()

    def test_client_raises_parse_error_on_invalid_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})

        client = self._mock_client(handler)
        with self.assertRaises(PolymarketParseError):
            client.get_market("mkt_1")
        client.close()

    def test_execution_adapter_stays_non_autonomous(self) -> None:
        adapter = SemiAutoExecutionAdapter()
        request = OrderRequest(market_id="mkt_1", side="yes", size_usd=25.0, limit_price=0.5)
        prepared = adapter.prepare_order(request)
        submitted = adapter.submit_order(request)
        simulated = adapter.simulate_order(request)
        self.assertTrue(prepared.accepted)
        self.assertFalse(submitted.accepted)
        self.assertTrue(simulated.accepted)
        self.assertEqual(simulated.stage, "simulated_filled")

    def test_paper_execution_adapter_simulates_fill_metadata(self) -> None:
        adapter = PaperExecutionAdapter()
        request = OrderRequest(market_id="mkt_1", side="yes", size_usd=75.0, limit_price=0.5)
        result = adapter.simulate_order(request)
        self.assertEqual(result.stage, "simulated_filled")
        self.assertEqual(result.reference_price, 0.5)
        self.assertEqual(result.filled_size_usd, 75.0)
        self.assertIsNotNone(result.fill_timestamp)
        self.assertEqual(len(result.fill_fragments), 2)

    def test_paper_execution_adapter_uses_bid_ask_and_expiry_cancel_paths(self) -> None:
        adapter = PaperExecutionAdapter()
        bid_ask = adapter.simulate_order(
            OrderRequest(
                market_id="mkt_1",
                side="yes",
                size_usd=40.0,
                limit_price=0.5,
                best_bid=0.49,
                best_ask=0.52,
            )
        )
        self.assertEqual(bid_ask.reference_price, 0.52)
        self.assertGreaterEqual(bid_ask.simulated_price, 0.52)

        expired = adapter.simulate_order(
            OrderRequest(
                market_id="mkt_1",
                side="yes",
                size_usd=120.0,
                limit_price=0.5,
                ttl_ms=500,
            )
        )
        self.assertEqual(expired.stage, "simulated_expired")
        self.assertGreater(expired.filled_size_usd, 0.0)
        self.assertEqual(expired.completion_reason, "ttl_expired")

        cancelled = adapter.simulate_order(
            OrderRequest(
                market_id="mkt_1",
                side="yes",
                size_usd=140.0,
                limit_price=0.5,
                cancel_after_ms=700,
            )
        )
        self.assertEqual(cancelled.stage, "simulated_cancelled")
        self.assertEqual(cancelled.completion_reason, "operator_cancelled")


if __name__ == "__main__":
    unittest.main()
