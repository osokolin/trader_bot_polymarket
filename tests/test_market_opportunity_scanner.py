from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.models import Market, MarketDataSnapshot, OpportunityCandidate, OpportunityScanResult, OrderBookSnapshot
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.utils.time import utc_now


class _FakeMarketCatalogService:
    def __init__(self, markets) -> None:
        self.markets = markets

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
        return self.markets[:limit]


class _FailingMarketCatalogService:
    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
        raise RuntimeError("gamma unavailable")


class _FakeMarketDataService:
    def __init__(self, snapshots: dict[str, MarketDataSnapshot], failures: dict[str, Exception] | None = None) -> None:
        self.snapshots = snapshots
        self.failures = failures or {}

    def inspect_snapshot(self, market_id: str, refresh: bool = False) -> MarketDataSnapshot:
        if market_id in self.failures:
            raise self.failures[market_id]
        return self.snapshots[market_id]


class _MarketSummary:
    def __init__(
        self,
        market_id: str,
        question: str,
        category: str = "crypto",
        liquidity_usd: float | None = 10000.0,
        enable_order_book: bool = True,
    ) -> None:
        self.market_id = market_id
        self.question = question
        self.event_id = None
        self.slug = None
        self.category = category
        self.active = True
        self.closed = False
        self.archived = False
        self.enable_order_book = enable_order_book
        self.liquidity_usd = liquidity_usd
        self.volume_usd = None


def _build_snapshot(
    market_id: str,
    *,
    midpoint: float,
    reference_price: float,
    liquidity_usd: float = 15000.0,
    rules_confidence: float = 0.9,
    spread_pct: float = 0.01,
) -> MarketDataSnapshot:
    now = utc_now()
    market = Market(
        market_id=market_id,
        title=f"Market {market_id}",
        category="crypto",
        liquidity_usd=liquidity_usd,
        spread_pct=spread_pct,
        resolution_time=now + timedelta(days=30),
        rules_text="Clear rules",
        rules_confidence=rules_confidence,
        has_orderbook=True,
    )
    orderbook = OrderBookSnapshot(
        market_id=market_id,
        best_bid=round(midpoint - 0.01, 4),
        best_ask=round(midpoint + 0.01, 4),
        midpoint=midpoint,
        spread_pct=spread_pct,
        timestamp=now,
    )
    return MarketDataSnapshot(
        snapshot_id=f"msnap_{market_id}",
        market_id=market_id,
        asset_id=f"asset_{market_id}",
        market=market,
        orderbook=orderbook,
        observed_at=now,
        fetched_at=now,
        source="inspection",
        stale=False,
        data_age_seconds=0,
        reference_price=reference_price,
        pricing_metadata={},
        websocket_payload={},
    )


class MarketOpportunityScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"), profile="balanced")

    def test_positive_opportunity_detected(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService([_MarketSummary("m1", "M1")]),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({"m1": _build_snapshot("m1", midpoint=0.45, reference_price=0.65)}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, limit=10)
        self.assertEqual(len(result.opportunities), 1)
        self.assertEqual(result.opportunities[0].market_id, "m1")
        self.assertGreater(result.opportunities[0].edge, 0.05)

    def test_negative_no_opportunity_filtered_out(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService([_MarketSummary("m1", "M1")]),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({"m1": _build_snapshot("m1", midpoint=0.50, reference_price=0.50)}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, limit=10)
        self.assertEqual(result.opportunities, [])

    def test_min_edge_filtering(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService([_MarketSummary("m1", "M1")]),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({"m1": _build_snapshot("m1", midpoint=0.45, reference_price=0.55)}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, min_edge=0.10, limit=10)
        self.assertEqual(result.opportunities, [])

    def test_min_liquidity_filtering(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService([_MarketSummary("m1", "M1", liquidity_usd=500.0)]),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({"m1": _build_snapshot("m1", midpoint=0.40, reference_price=0.70, liquidity_usd=500.0)}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, min_liquidity=1000.0, limit=10)
        self.assertEqual(result.opportunities, [])
        self.assertEqual(result.scanned_count, 0)

    def test_limit_behavior_sorts_by_absolute_edge_then_confidence(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService(
                [
                    _MarketSummary("m1", "M1"),
                    _MarketSummary("m2", "M2"),
                    _MarketSummary("m3", "M3"),
                ]
            ),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService(
                {
                    "m1": _build_snapshot("m1", midpoint=0.40, reference_price=0.70, rules_confidence=0.95),
                    "m2": _build_snapshot("m2", midpoint=0.42, reference_price=0.60, rules_confidence=0.90),
                    "m3": _build_snapshot("m3", midpoint=0.55, reference_price=0.35, rules_confidence=0.92),
                }
            ),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, limit=2)
        self.assertEqual(len(result.opportunities), 2)
        self.assertEqual([item.market_id for item in result.opportunities], ["m1", "m3"])

    def test_structured_failure_handling_without_traceback(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FakeMarketCatalogService([_MarketSummary("m1", "M1")]),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({}, failures={"m1": RuntimeError("hidden details")}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, limit=10)
        self.assertEqual(result.opportunities, [])
        self.assertEqual(len(result.warning_messages), 1)
        self.assertIn("m1: hidden details", result.warning_messages[0])

    def test_catalog_failure_returns_structured_warning(self) -> None:
        service = MarketOpportunityScannerService(
            market_catalog_service=_FailingMarketCatalogService(),  # type: ignore[arg-type]
            market_data_service=_FakeMarketDataService({}),  # type: ignore[arg-type]
        )
        result = service.scan(self.settings, limit=10)
        self.assertEqual(result.opportunities, [])
        self.assertEqual(result.warning_messages, ["scan_unavailable: gamma unavailable"])

    def test_cli_output_is_operator_readable(self) -> None:
        fake_result = OpportunityScanResult(
            opportunities=[
                OpportunityCandidate(
                    market_id="m1",
                    market_title="Market m1",
                    category="crypto",
                    market_price=0.4500,
                    fair_probability=0.5500,
                    edge=0.1000,
                    confidence=0.8800,
                    liquidity_usd=12000.0,
                    source="inspection",
                )
            ],
            scanned_count=5,
            skipped_count=1,
            warning_messages=["m2: stale snapshot"],
        )
        with patch.dict(os.environ, {"BOT_DATABASE_URL": "sqlite:///bot.db"}, clear=False), patch(
            "bot.cli.app.MarketOpportunityScannerService"
        ) as scanner_cls:
            scanner_cls.return_value.scan.return_value = fake_result
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["--config-dir", "config", "markets", "scan", "--limit", "5"])
            output = buffer.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Market opportunity scan", output)
            self.assertIn("opportunity_count: 1", output)
            self.assertIn("market_id=m1", output)
            self.assertIn("warning: m2: stale snapshot", output)
            self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
