from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import httpx

from bot.adapters.polymarket.clob_client import ClobMarketDataClient, PolymarketOrderBookAdapter
from bot.adapters.polymarket.errors import (
    PolymarketHTTPError,
    PolymarketParseError,
    PolymarketStaleDataError,
    PolymarketTransportError,
)
from bot.adapters.polymarket.gamma_client import GammaApiClient, PolymarketMarketMetadataAdapter
from bot.adapters.polymarket.models import OrderRequest
from bot.adapters.polymarket.websocket_market import PublicMarketWebSocketClient
from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import ProposalStatus, SourceType
from bot.domain.models import Market, MarketDataSnapshot, OrderBookSnapshot, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.approval_snapshot_provider import PolymarketApprovalSnapshotProvider
from bot.services.market_sync import LiveMarketDataService
from bot.services.probability_engine import EdgeAdjustedProbabilityProvider
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, MarketDataSnapshotRepository, ProposalRepository
from bot.ui import OperatorDashboardApp, OperatorDashboardServices
from bot.utils.time import utc_now


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


class _HangingWebSocket(_FakeWebSocket):
    async def recv(self):
        await __import__("asyncio").sleep(0.02)
        return await super().recv()


def _snapshot(market_id: str = "mkt_1", source: str = "cache", age_seconds: int = 0) -> MarketDataSnapshot:
    now = utc_now() - timedelta(seconds=age_seconds)
    return MarketDataSnapshot(
        snapshot_id="msnap_1",
        market_id=market_id,
        asset_id="asset_1",
        market=Market(
            market_id=market_id,
            title="Will BTC close above 100k?",
            category="crypto",
            liquidity_usd=15000,
            spread_pct=0.02,
            resolution_time=utc_now() + timedelta(days=30),
            rules_text="Clear rules",
            rules_confidence=0.95,
            has_orderbook=True,
        ),
        orderbook=OrderBookSnapshot(
            market_id=market_id,
            best_bid=0.48,
            best_ask=0.52,
            midpoint=0.5,
            spread_pct=0.08,
            timestamp=now,
        ),
        observed_at=now,
        fetched_at=utc_now(),
        source=source,
        stale=age_seconds > 120,
        data_age_seconds=age_seconds,
        reference_price=0.505,
        pricing_metadata={"price_status": "available"},
        websocket_payload={},
    )


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
        seen_paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
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
            if request.url.path == "/midpoint":
                return httpx.Response(200, json={"midpoint": "0.5"})
            if request.url.path == "/price":
                return httpx.Response(200, json={"price": "0.51"})
            raise AssertionError(f"unexpected path: {request.url.path}")

        client = self._mock_clob_client(handler)
        adapter = PolymarketOrderBookAdapter(client)
        book = adapter.get_orderbook("asset_1", market_id="mkt_1")
        self.assertEqual(book.snapshot.midpoint, 0.5)
        self.assertEqual(book.reference_price, 0.51)
        self.assertEqual(seen_paths, ["/book", "/midpoint", "/price"])
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
            if request.url.path == "/midpoint":
                return httpx.Response(200, json={"midpoint": "0.5"})
            if request.url.path == "/price":
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
                self.assertEqual(cached.reference_price, 0.505)
                self.assertFalse(cached.stale)
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
            if request.url.path == "/midpoint":
                return httpx.Response(200, json={"midpoint": "0.5"})
            if request.url.path == "/price":
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

    def test_live_market_data_service_rejects_stale_cached_snapshot_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                repository = MarketDataSnapshotRepository(connection)
                repository.save(_snapshot(age_seconds=3600))
                service = LiveMarketDataService(
                    PolymarketMarketMetadataAdapter(self._mock_gamma_client(lambda request: httpx.Response(200, json=[]))),
                    PolymarketOrderBookAdapter(self._mock_clob_client(lambda request: httpx.Response(200, json={}))),
                    repository,
                    stale_after_seconds=120,
                )
                with self.assertRaises(PolymarketStaleDataError):
                    service.latest_cached_snapshot("mkt_1", fail_on_stale=True)
            finally:
                connection.close()

    def test_public_market_websocket_reconnects_and_parses_update(self) -> None:
        calls = []

        async def connector(url: str):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("temporary network issue")
            return _FakeWebSocket(
                [
                    '[{"asset_id":"asset_1","best_bid":"0.49","best_ask":"0.51","timestamp":"2026-03-11T09:00:00Z","price":"0.50"}]'
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

    def test_public_market_websocket_times_out_and_reconnects(self) -> None:
        attempts = []

        async def connector(url: str):
            attempts.append(url)
            if len(attempts) == 1:
                return _HangingWebSocket(["[]"])
            return _FakeWebSocket(['[{"asset_id":"asset_1","best_bid":"0.49","best_ask":"0.51","timestamp":"2026-03-11T09:00:00Z","price":"0.50"}]'])

        sleeps = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        client = PublicMarketWebSocketClient(
            connector=connector,
            sleep_func=fake_sleep,
            recv_timeout_seconds=0.001,
            max_reconnect_attempts=2,
        )
        updates = __import__("asyncio").run(client.stream_market(["asset_1"]))
        self.assertEqual(len(updates), 1)
        self.assertEqual(sleeps, [0.25])

    def test_public_market_websocket_rejects_malformed_payload(self) -> None:
        async def connector(url: str):
            return _FakeWebSocket(['{"asset_id":"asset_1","best_bid":"oops"}'])

        client = PublicMarketWebSocketClient(connector=connector)
        with self.assertRaises(PolymarketParseError):
            __import__("asyncio").run(client.stream_market(["asset_1"]))

    def test_public_market_websocket_subscription_uses_expected_endpoint_and_asset_ids(self) -> None:
        payloads = []

        async def connector(url: str):
            self.assertEqual(url, "wss://ws-subscriptions-clob.polymarket.com/ws/")
            socket = _FakeWebSocket(['[{"asset_id":"asset_1","best_bid":"0.49","best_ask":"0.51","timestamp":"2026-03-11T09:00:00Z"}]'])
            original_send = socket.send

            async def wrapped_send(payload: str) -> None:
                payloads.append(payload)
                await original_send(payload)

            socket.send = wrapped_send  # type: ignore[assignment]
            return socket

        client = PublicMarketWebSocketClient(connector=connector)
        __import__("asyncio").run(client.stream_market(["asset_1"]))
        self.assertEqual(payloads, ['{"asset_ids": ["asset_1"], "type": "market"}'])

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

    def test_cli_live_market_commands_use_cache_first_and_stream_service(self) -> None:
        class FakeLiveMarketDataService:
            instances = []

            def __init__(self, *args, **kwargs) -> None:
                self.calls = []
                self.cached = _snapshot(source="cache", age_seconds=30)
                self.stale_after_seconds = 120
                FakeLiveMarketDataService.instances.append(self)

            def inspect_snapshot(self, market_id: str, refresh: bool = False):
                self.calls.append(("inspect", market_id, refresh))
                return _snapshot(market_id=market_id, source="inspection" if refresh else "cache", age_seconds=30)

            def latest_cached_snapshot(self, market_id: str, fail_on_stale: bool = False):
                self.calls.append(("cache", market_id, fail_on_stale))
                return self.cached

        class FakeRealtimeMarketFeedService:
            instances = []

            def __init__(self, *args, **kwargs) -> None:
                self.calls = []
                FakeRealtimeMarketFeedService.instances.append(self)

            async def refresh_from_websocket(self, market_id: str, max_messages: int = 1):
                self.calls.append((market_id, max_messages))
                return _snapshot(market_id=market_id, source="websocket", age_seconds=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cli.db"
            env = {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}
            with patch.dict(os.environ, env, clear=False), \
                patch("bot.cli.app.LiveMarketDataService", FakeLiveMarketDataService), \
                patch("bot.cli.app.RealtimeMarketFeedService", FakeRealtimeMarketFeedService):
                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "markets", "live", "mkt_cli"])
                self.assertEqual(exit_code, 0)
                self.assertIn("source: cache", out.getvalue())
                self.assertEqual(FakeLiveMarketDataService.instances[-1].calls[0], ("inspect", "mkt_cli", False))

                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "markets", "stream-once", "mkt_cli"])
                self.assertEqual(exit_code, 0)
                self.assertIn("source: websocket", out.getvalue())
                self.assertEqual(FakeRealtimeMarketFeedService.instances[-1].calls[0], ("mkt_cli", 1))

    def test_cli_market_and_event_catalog_commands(self) -> None:
        class FakeLiveMarketDataService:
            def __init__(self, *args, **kwargs) -> None:
                self.stale_after_seconds = 120

            def inspect_snapshot(self, market_id: str, refresh: bool = False):
                return _snapshot(market_id=market_id, source="cache", age_seconds=30)

            def latest_cached_snapshot(self, market_id: str, fail_on_stale: bool = False):
                return _snapshot(market_id=market_id, source="cache", age_seconds=30)

        class FakeRealtimeMarketFeedService:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def refresh_from_websocket(self, market_id: str, max_messages: int = 1):
                return _snapshot(market_id=market_id, source="websocket", age_seconds=0)

        class FakeMarketCatalogService:
            instances = []

            def __init__(self, *args, **kwargs) -> None:
                self.market_calls = []
                self.event_calls = []
                FakeMarketCatalogService.instances.append(self)

            def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
                from bot.adapters.polymarket.models import GammaMarketSummary
                self.market_calls.append((limit, active, closed))

                return [
                    GammaMarketSummary(
                        market_id="mkt_cli_1",
                        question="Will CPI print below consensus?",
                        event_id="evt_macro",
                        slug="cpi-below-consensus",
                        category="macro",
                        active=active,
                        closed=closed,
                        archived=False,
                        enable_order_book=True,
                        liquidity_usd=1234.0,
                        volume_usd=5678.0,
                    )
                ][:limit]

            def list_events(self, limit: int = 20, active: bool = True, closed: bool = False):
                from bot.adapters.polymarket.models import GammaEventSummary
                self.event_calls.append((limit, active, closed))

                return [
                    GammaEventSummary(
                        event_id="evt_macro",
                        title="Macro Calendar",
                        slug="macro-calendar",
                        active=active,
                        closed=closed,
                        archived=False,
                        market_count=3,
                    )
                ][:limit]

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cli.db"
            env = {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}
            with patch.dict(os.environ, env, clear=False), \
                patch("bot.cli.app.LiveMarketDataService", FakeLiveMarketDataService), \
                patch("bot.cli.app.RealtimeMarketFeedService", FakeRealtimeMarketFeedService), \
                patch("bot.cli.app.MarketCatalogService", FakeMarketCatalogService):
                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "markets", "catalog", "--limit", "10"])
                self.assertEqual(exit_code, 0)
                self.assertIn("market_count: 1", out.getvalue())
                self.assertIn("market_id=mkt_cli_1", out.getvalue())
                self.assertIn("question=Will CPI print below consensus?", out.getvalue())
                self.assertEqual(FakeMarketCatalogService.instances[-1].market_calls[-1], (10, True, False))

                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "events", "catalog", "--limit", "10"])
                self.assertEqual(exit_code, 0)
                self.assertIn("event_count: 1", out.getvalue())
                self.assertIn("event_id=evt_macro", out.getvalue())
                self.assertIn("title=Macro Calendar", out.getvalue())
                self.assertEqual(FakeMarketCatalogService.instances[-1].event_calls[-1], (10, True, False))

    def test_cli_catalog_closed_scope_semantics(self) -> None:
        class FakeLiveMarketDataService:
            def __init__(self, *args, **kwargs) -> None:
                self.stale_after_seconds = 120

        class FakeRealtimeMarketFeedService:
            def __init__(self, *args, **kwargs) -> None:
                pass

        class FakeMarketCatalogService:
            instances = []

            def __init__(self, *args, **kwargs) -> None:
                self.market_calls = []
                self.event_calls = []
                FakeMarketCatalogService.instances.append(self)

            def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
                self.market_calls.append((limit, active, closed))
                return []

            def list_events(self, limit: int = 20, active: bool = True, closed: bool = False):
                self.event_calls.append((limit, active, closed))
                return []

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cli.db"
            env = {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}
            with patch.dict(os.environ, env, clear=False), \
                patch("bot.cli.app.LiveMarketDataService", FakeLiveMarketDataService), \
                patch("bot.cli.app.RealtimeMarketFeedService", FakeRealtimeMarketFeedService), \
                patch("bot.cli.app.MarketCatalogService", FakeMarketCatalogService):
                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "markets", "catalog", "--scope", "closed"])
                self.assertEqual(exit_code, 0)
                self.assertEqual(FakeMarketCatalogService.instances[-1].market_calls[-1], (20, False, True))

                out = StringIO()
                with redirect_stdout(out):
                    exit_code = main(["--config-dir", "config", "events", "catalog", "--scope", "closed"])
                self.assertEqual(exit_code, 0)
                self.assertEqual(FakeMarketCatalogService.instances[-1].event_calls[-1], (20, False, True))

    def test_market_catalog_service_raises_structured_parse_error_on_malformed_numeric_payload(self) -> None:
        class FakeGammaClient:
            def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
                return [
                    {
                        "id": "mkt_bad",
                        "question": "Bad numeric payload",
                        "category": "crypto",
                        "active": True,
                        "closed": False,
                        "archived": False,
                        "enableOrderBook": True,
                        "liquidityClob": "not-a-number",
                    }
                ]

            def list_events(self, limit: int = 20, active: bool = True, closed: bool = False):
                return []

        from bot.services.market_catalog import MarketCatalogService

        service = MarketCatalogService(FakeGammaClient())  # type: ignore[arg-type]
        with self.assertRaises(PolymarketParseError):
            service.list_markets()

    def test_ui_live_market_route_uses_cache_first_inspection(self) -> None:
        class FakeMarketDataService:
            def __init__(self) -> None:
                self.calls = []

            def inspect_snapshot(self, market_id: str, refresh: bool = False):
                self.calls.append(("inspect", market_id, refresh))
                return _snapshot(market_id=market_id, source="cache", age_seconds=20)

            def latest_cached_snapshot(self, market_id: str, fail_on_stale: bool = False):
                self.calls.append(("cache", market_id, fail_on_stale))
                return _snapshot(market_id=market_id, source="cache", age_seconds=20)

        fake_market_data = FakeMarketDataService()
        app = OperatorDashboardApp(
            OperatorDashboardServices(
                proposal_service=object(),  # type: ignore[arg-type]
                execution_service=object(),  # type: ignore[arg-type]
                notifications_service=object(),  # type: ignore[arg-type]
                decision_review_service=object(),  # type: ignore[arg-type]
                execution_evaluation_service=object(),  # type: ignore[arg-type]
                outcome_analysis_service=object(),  # type: ignore[arg-type]
                saved_view_service=object(),  # type: ignore[arg-type]
                reporting_service=object(),  # type: ignore[arg-type]
                market_data_service=fake_market_data,  # type: ignore[arg-type]
            )
        )
        status, body = app.render_response("/markets/live/mkt_ui")
        self.assertEqual(status, "200 OK")
        self.assertIn("Рыночные live-данные", body)
        self.assertIn("обновить сейчас", body)
        self.assertEqual(fake_market_data.calls[0], ("inspect", "mkt_ui", False))

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
