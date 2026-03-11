from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import httpx

from bot.adapters.polymarket.client import (
    ClobMarketDataClient,
    GammaApiClient,
    PolymarketHTTPError,
    PolymarketMarketMetadataAdapter,
    PolymarketParseError,
    PolymarketStaleDataError,
    PolymarketTransportError,
)
from bot.adapters.polymarket.market_stream import PolymarketOrderBookAdapter, PublicMarketWebSocketClient
from bot.adapters.polymarket.models import OrderRequest
from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.domain.enums import ProposalStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.market_data import LiveMarketDataService, PolymarketApprovalSnapshotProvider
from bot.services.probability_engine import EdgeAdjustedProbabilityProvider
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, MarketDataSnapshotRepository, ProposalRepository


class _FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self):
        if not self.messages:
            raise RuntimeError("no more messages")
        next_item = self.messages.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


class PolymarketAdaptersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))

    def _mock_gamma_client(self, handler) -> GammaApiClient:
        return GammaApiClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def _mock_clob_client(self, handler) -> ClobMarketDataClient:
        return ClobMarketDataClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_gamma_market_metadata_adapter_maps_market(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/markets")
            payload = [
                {
                    "id": "mkt_1",
                    "question": "Will BTC close above 100k?",
                    "category": "crypto",
                    "liquidityClob": 15000,
                    "spread": 0.02,
                    "endDate": "2026-04-01T00:00:00Z",
                    "description": "Clear resolution rules",
                    "rulesConfidence": 0.95,
                    "tags": ["crypto"],
                    "enableOrderBook": True,
                    "eventId": "evt_1",
                    "clobTokenId": "asset_1",
                    "active": True,
                    "closed": False,
                    "archived": False,
                    "lastTradePrice": 0.49,
                }
            ]
            return httpx.Response(200, json=payload)

        client = self._mock_gamma_client(handler)
        adapter = PolymarketMarketMetadataAdapter(client)
        metadata = adapter.get_market_metadata("mkt_1")
        self.assertEqual(metadata.market.market_id, "mkt_1")
        self.assertEqual(metadata.market.event_id, "evt_1")
        self.assertEqual(metadata.asset_id, "asset_1")
        self.assertEqual(metadata.market.last_traded_price, 0.49)
        client.close()

    def test_orderbook_adapter_maps_public_clob_book(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/book":
                return httpx.Response(
                    200,
                    json={
                        "asset_id": "asset_1",
                        "bids": [{"price": "0.48", "size": "100"}],
                        "asks": [{"price": "0.52", "size": "120"}],
                        "timestamp": "2026-03-11T09:00:00Z",
                    },
                )
            if request.url.path == "/last-trade-price":
                return httpx.Response(200, json={"price": "0.51"})
            raise AssertionError(f"unexpected path: {request.url.path}")

        client = self._mock_clob_client(handler)
        adapter = PolymarketOrderBookAdapter(client)
        book = adapter.get_orderbook("asset_1", market_id="mkt_1")
        self.assertEqual(book.snapshot.midpoint, 0.5)
        self.assertEqual(book.last_trade_price, 0.51)
        client.close()

    def test_gamma_client_raises_transport_error_on_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        client = self._mock_gamma_client(handler)
        with self.assertRaises(PolymarketTransportError):
            client.get_market("mkt_1")
        client.close()

    def test_clob_client_raises_http_error_on_bad_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        client = self._mock_clob_client(handler)
        with self.assertRaises(PolymarketHTTPError):
            client.get_orderbook("asset_1")
        client.close()

    def test_adapter_raises_parse_error_on_malformed_market_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "mkt_1", "question": "bad payload"}])

        client = self._mock_gamma_client(handler)
        adapter = PolymarketMarketMetadataAdapter(client)
        with self.assertRaises(PolymarketParseError):
            adapter.get_market_metadata("mkt_1")
        client.close()

    def test_live_market_data_service_persists_snapshot_cache(self) -> None:
        gamma_client = self._mock_gamma_client(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "id": "mkt_1",
                        "question": "Will BTC close above 100k?",
                        "category": "crypto",
                        "liquidityClob": 15000,
                        "spread": 0.02,
                        "endDate": "2026-04-01T00:00:00Z",
                        "description": "Clear resolution rules",
                        "rulesConfidence": 0.95,
                        "tags": ["crypto"],
                        "enableOrderBook": True,
                        "eventId": "evt_1",
                        "clobTokenId": "asset_1",
                    }
                ],
            )
        )

        def clob_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/book":
                return httpx.Response(
                    200,
                    json={
                        "asset_id": "asset_1",
                        "bids": [{"price": "0.48", "size": "100"}],
                        "asks": [{"price": "0.52", "size": "120"}],
                        "timestamp": "2026-03-11T09:00:00+00:00",
                    },
                )
            if request.url.path == "/last-trade-price":
                return httpx.Response(200, json={"price": "0.505"})
            raise AssertionError(f"unexpected path: {request.url.path}")

        clob_client = self._mock_clob_client(clob_handler)
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = LiveMarketDataService(
                    PolymarketMarketMetadataAdapter(gamma_client),
                    PolymarketOrderBookAdapter(clob_client),
                    MarketDataSnapshotRepository(connection),
                    stale_after_seconds=999999999,
                )
                snapshot = service.fetch_live_snapshot("mkt_1")
                cached = service.latest_cached_snapshot("mkt_1")
                self.assertIsNotNone(cached)
                self.assertEqual(cached.snapshot_id, snapshot.snapshot_id)
                self.assertEqual(cached.asset_id, "asset_1")
            finally:
                connection.close()
                gamma_client.close()
                clob_client.close()

    def test_live_market_data_service_fails_closed_on_stale_snapshot(self) -> None:
        gamma_client = self._mock_gamma_client(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "id": "mkt_1",
                        "question": "Will BTC close above 100k?",
                        "category": "crypto",
                        "liquidityClob": 15000,
                        "spread": 0.02,
                        "endDate": "2026-04-01T00:00:00Z",
                        "description": "Clear resolution rules",
                        "rulesConfidence": 0.95,
                        "enableOrderBook": True,
                        "clobTokenId": "asset_1",
                    }
                ],
            )
        )

        def clob_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/book":
                return httpx.Response(
                    200,
                    json={
                        "asset_id": "asset_1",
                        "bids": [{"price": "0.48"}],
                        "asks": [{"price": "0.52"}],
                        "timestamp": "2026-03-11T09:00:00Z",
                    },
                )
            if request.url.path == "/last-trade-price":
                return httpx.Response(200, json={"price": "0.50"})
            raise AssertionError(f"unexpected path: {request.url.path}")

        clob_client = self._mock_clob_client(clob_handler)
        service = LiveMarketDataService(
            PolymarketMarketMetadataAdapter(gamma_client),
            PolymarketOrderBookAdapter(clob_client),
            stale_after_seconds=1,
        )
        with self.assertRaises(PolymarketStaleDataError):
            service.fetch_live_snapshot("mkt_1")
        gamma_client.close()
        clob_client.close()

    def test_public_market_websocket_reconnects_and_parses_update(self) -> None:
        calls = []

        async def connector(url: str):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("temporary network issue")
            return _FakeWebSocket(
                [
                    '[{"asset_id":"asset_1","best_bid":"0.49","best_ask":"0.51","timestamp":"2026-03-11T09:00:00Z","last_trade_price":"0.50"}]'
                ]
            )

        sleeps = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        client = PublicMarketWebSocketClient(
            connector=connector,
            sleep_func=fake_sleep,
            max_reconnect_attempts=2,
        )
        updates = __import__("asyncio").run(client.stream_market(["asset_1"]))
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].asset_id, "asset_1")
        self.assertEqual(updates[0].midpoint, 0.5)
        self.assertEqual(sleeps, [0.25])

    def test_public_market_websocket_rejects_malformed_payload(self) -> None:
        async def connector(url: str):
            return _FakeWebSocket(['{"asset_id":"asset_1","best_bid":"oops"}'])

        client = PublicMarketWebSocketClient(connector=connector)
        with self.assertRaises(PolymarketParseError):
            __import__("asyncio").run(client.stream_market(["asset_1"]))

    def test_approval_provider_fail_closed_on_live_market_error(self) -> None:
        def gamma_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "mkt_123",
                        "question": "Will BTC ETF inflows rise this month?",
                        "category": "crypto",
                        "liquidityClob": 12000,
                        "spread": 0.01,
                        "endDate": "2026-03-30T00:00:00Z",
                        "description": "Clear",
                        "rulesConfidence": 0.95,
                        "enableOrderBook": True,
                        "clobTokenId": "asset_123",
                    }
                ],
            )

        def clob_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        gamma_client = self._mock_gamma_client(gamma_handler)
        clob_client = self._mock_clob_client(clob_handler)
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        self.addCleanup(lambda: os.path.exists(temp_db.name) and os.unlink(temp_db.name))
        database = Database(Path(temp_db.name))
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        provider = PolymarketApprovalSnapshotProvider(
            LiveMarketDataService(
                PolymarketMarketMetadataAdapter(gamma_client),
                PolymarketOrderBookAdapter(clob_client),
                MarketDataSnapshotRepository(connection),
            ),
            EdgeAdjustedProbabilityProvider(),
        )
        service = ProposalLifecycleService(
            ProposalRepository(connection),
            AuditLogService(AuditRepository(connection)),
            ProposalEngine(),
            snapshot_provider=provider,
        )
        market = Market(
            market_id="mkt_123",
            title="Will BTC ETF inflows rise this month?",
            category="crypto",
            liquidity_usd=12000,
            spread_pct=0.01,
            resolution_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(days=3),
            rules_text="Clear",
            rules_confidence=0.95,
            tags=["crypto"],
            has_orderbook=True,
        )
        probability = ProbabilityEstimate(
            market_id="mkt_123",
            fair_probability=0.64,
            confidence=0.84,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )
        proposal = service.create(self.settings, service.proposal_engine.create_default_context(market, probability, current_price=0.55))
        with self.assertRaises(ProposalLifecycleError):
            service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
            )
        stored = service.get(proposal.proposal_id)
        self.assertEqual(stored.status, ProposalStatus.PENDING_MANUAL_CONFIRMATION)
        gamma_client.close()
        clob_client.close()

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


if __name__ == "__main__":
    unittest.main()
