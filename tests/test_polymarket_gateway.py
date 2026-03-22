from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from bot.adapters.polymarket.clob_client import ClobMarketDataClient
from bot.adapters.polymarket.gamma_client import GammaApiClient
from bot.bootstrap import build_app_container
from bot.config.loader import load_settings
from bot.domain.enums import BotMode
from bot.integrations.polymarket_gateway import (
    PolymarketGateway,
    PolymarketGatewayConfigError,
    PolymarketGatewayOrder,
)
from bot.security.trading_signer import TradingSigner, TradingSignerError


class PolymarketGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))

    def _gamma_client(self) -> GammaApiClient:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path != "/markets":
                raise AssertionError(f"unexpected path: {request.url.path}")
            market_id = request.url.params.get("id")
            slug = request.url.params.get("slug")
            limit = request.url.params.get("limit")
            if market_id == "mkt_1" or slug == "btc-above-100k":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "mkt_1",
                            "question": "Will BTC close above 100k?",
                            "slug": "btc-above-100k",
                            "category": "crypto",
                            "liquidityClob": 15000,
                            "spread": 0.02,
                            "endDate": "2026-04-01T00:00:00Z",
                            "description": "Resolves YES if BTC/USD exceeds 100k.",
                            "rulesConfidence": 0.95,
                            "tags": ["crypto"],
                            "enableOrderBook": True,
                            "eventId": "evt_1",
                            "event": {"title": "BTC price milestones"},
                            "clobTokenId": "asset_1",
                            "active": True,
                            "closed": False,
                            "archived": False,
                            "lastTradePrice": 0.49,
                        }
                    ],
                )
            if limit is not None:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "mkt_1",
                            "question": "Will BTC close above 100k?",
                            "slug": "btc-above-100k",
                            "category": "crypto",
                            "liquidityClob": 15000,
                            "spread": 0.02,
                            "endDate": "2026-04-01T00:00:00Z",
                            "description": "Resolves YES if BTC/USD exceeds 100k.",
                            "rulesConfidence": 0.95,
                            "tags": ["crypto"],
                            "enableOrderBook": True,
                            "eventId": "evt_1",
                            "event": {"title": "BTC price milestones"},
                            "clobTokenId": "asset_1",
                            "active": True,
                            "closed": False,
                            "archived": False,
                            "lastTradePrice": 0.49,
                        }
                    ],
                )
            raise AssertionError(f"unexpected params: {request.url.params!r}")

        return GammaApiClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def _clob_client(self) -> ClobMarketDataClient:
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
            if request.url.path == "/midpoint":
                return httpx.Response(200, json={"midpoint": "0.50"})
            if request.url.path == "/price":
                return httpx.Response(200, json={"price": "0.51"})
            raise AssertionError(f"unexpected path: {request.url.path}")

        return ClobMarketDataClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def _gateway(self, *, enabled: bool = True, dry_run: bool = True) -> PolymarketGateway:
        config = replace(
            self.settings.polymarket_gateway,
            enable_polymarket_gateway=enabled,
            dry_run=dry_run,
            allow_live_order_submission=False,
        )
        return PolymarketGateway(
            config=config,
            signer=TradingSigner(),
            gamma_client=self._gamma_client(),
            clob_client=self._clob_client(),
        )

    def test_gateway_metadata_retrieval_and_candidate_listing(self) -> None:
        gateway = self._gateway()
        try:
            candidates = gateway.list_candidate_markets(limit=5)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].market_id, "mkt_1")
            self.assertEqual(candidates[0].category, "Crypto")

            metadata = gateway.get_market_metadata("mkt_1")
            self.assertEqual(metadata.market.market_id, "mkt_1")
            self.assertEqual(metadata.asset_id, "asset_1")
            self.assertEqual(metadata.slug, "btc-above-100k")
            self.assertEqual(metadata.event_title, "BTC price milestones")
        finally:
            gateway.close()

    def test_gateway_disabled_mode_fails_closed(self) -> None:
        gateway = self._gateway(enabled=False)
        try:
            with self.assertRaises(PolymarketGatewayConfigError):
                gateway.list_candidate_markets()
        finally:
            gateway.close()

    def test_gateway_dry_run_execution_surface_is_safe(self) -> None:
        gateway = self._gateway()
        try:
            quote = gateway.quote_order(
                PolymarketGatewayOrder(
                    market_id="mkt_1",
                    side="yes",
                    size_usd=25.0,
                    limit_price=0.50,
                )
            )
            self.assertTrue(quote.dry_run)
            self.assertEqual(quote.reference_price, 0.51)

            receipt = gateway.place_order(
                PolymarketGatewayOrder(
                    market_id="mkt_1",
                    side="yes",
                    size_usd=25.0,
                    limit_price=0.50,
                )
            )
            self.assertTrue(receipt.accepted)
            self.assertTrue(receipt.dry_run)
            self.assertIn("Dry-run only", receipt.message)
            self.assertEqual(gateway.get_open_orders(), [])
            self.assertEqual(gateway.get_positions(), [])
        finally:
            gateway.close()

    def test_trading_signer_redacts_secret_material(self) -> None:
        private_key = "0x" + ("1" * 64)
        signer = TradingSigner(
            private_key=private_key,
            api_key="key_123",
            api_secret="secret_456",
            api_passphrase="passphrase_789",
        )
        rendered = repr(signer)
        self.assertIn("private_key=set", rendered)
        self.assertNotIn(private_key, rendered)
        self.assertNotIn("secret_456", rendered)
        self.assertNotIn("passphrase_789", rendered)

    def test_trading_signer_error_does_not_echo_secret(self) -> None:
        bad_key = "super-secret-private-key"
        with self.assertRaises(TradingSignerError) as ctx:
            TradingSigner(private_key=bad_key)
        self.assertNotIn(bad_key, str(ctx.exception))

    def test_bootstrap_keeps_gateway_optional_and_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            container = build_app_container(
                self.settings,
                "balanced",
                Path(tmp_dir) / "bot.db",
                include_market_runtime=False,
                include_telegram_runtime=False,
            )
            try:
                self.assertIsNone(container.polymarket_gateway)
            finally:
                container.close()

    def test_bootstrap_fails_closed_when_live_gateway_lacks_credentials(self) -> None:
        original_env = dict(os.environ)
        for key in (
            self.settings.polymarket_gateway.private_key_env_var,
            self.settings.polymarket_gateway.api_key_env_var,
            self.settings.polymarket_gateway.api_secret_env_var,
            self.settings.polymarket_gateway.api_passphrase_env_var,
        ):
            os.environ.pop(key, None)
        live_settings = replace(
            self.settings,
            mode=BotMode.LIVE_SMALL,
            polymarket_gateway=replace(
                self.settings.polymarket_gateway,
                enable_polymarket_gateway=True,
                dry_run=False,
                allow_live_order_submission=True,
            ),
        )
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with self.assertRaises(TradingSignerError):
                    build_app_container(
                        live_settings,
                        "balanced",
                        Path(tmp_dir) / "bot.db",
                        include_market_runtime=False,
                        include_telegram_runtime=False,
                    )
        finally:
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == "__main__":
    unittest.main()
