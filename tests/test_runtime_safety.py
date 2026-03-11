from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from bot.adapters.polymarket.models import OrderRequest, OrderResult, SimulationResult
from bot.adapters.polymarket.trading import ExecutionAdapter, SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.domain.enums import BotMode
from bot.services.runtime_safety import build_runtime_safety_snapshot


class LiveCapableAdapter(ExecutionAdapter):
    supports_live_execution = True

    def prepare_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(accepted=True, order_id=None, message="prepared")

    def submit_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(accepted=True, order_id="ord_1", message="submitted")

    def simulate_order(self, request: OrderRequest) -> SimulationResult:
        return SimulationResult(
            stage="simulated_submitted",
            accepted=True,
            message="simulated",
            order_id="paper_1",
            reference_price=request.limit_price,
            simulated_price=request.limit_price,
            slippage_bps=0.0,
            filled_size_usd=0.0,
            fill_timestamp=None,
        )


class RuntimeSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))

    def test_semi_auto_snapshot_reports_all_live_execution_blockers(self) -> None:
        snapshot = build_runtime_safety_snapshot(
            self.settings,
            "balanced",
            SemiAutoExecutionAdapter(),
            open_positions=2,
            unresolved_exposure_usd=125.0,
        )
        self.assertFalse(snapshot.config_live_execution_enabled)
        self.assertFalse(snapshot.mode_supports_live_execution)
        self.assertFalse(snapshot.adapter_supports_live_execution)
        self.assertFalse(snapshot.guard_allows_live_execution)
        self.assertFalse(snapshot.live_execution_enabled)
        self.assertEqual(snapshot.live_execution_reason, "config disables live execution")
        self.assertTrue(snapshot.semi_auto_strict)

    def test_live_mode_snapshot_still_reports_disabled_when_adapter_cannot_submit(self) -> None:
        live_settings = replace(
            self.settings,
            mode=BotMode.LIVE_SMALL,
            approvals=replace(self.settings.approvals, auto_execute_disabled=False),
        )
        snapshot = build_runtime_safety_snapshot(
            live_settings,
            "balanced",
            SemiAutoExecutionAdapter(),
            open_positions=0,
            unresolved_exposure_usd=0.0,
        )
        self.assertTrue(snapshot.config_live_execution_enabled)
        self.assertTrue(snapshot.mode_supports_live_execution)
        self.assertFalse(snapshot.adapter_supports_live_execution)
        self.assertFalse(snapshot.live_execution_enabled)
        self.assertEqual(snapshot.live_execution_reason, "execution adapter does not support live submission")

    def test_live_mode_snapshot_still_reports_manual_guard_block_when_stack_is_capable(self) -> None:
        live_settings = replace(
            self.settings,
            mode=BotMode.LIVE_SMALL,
            approvals=replace(self.settings.approvals, auto_execute_disabled=False),
        )
        snapshot = build_runtime_safety_snapshot(
            live_settings,
            "balanced",
            LiveCapableAdapter(),
            open_positions=0,
            unresolved_exposure_usd=0.0,
        )
        self.assertTrue(snapshot.config_live_execution_enabled)
        self.assertTrue(snapshot.mode_supports_live_execution)
        self.assertTrue(snapshot.adapter_supports_live_execution)
        self.assertFalse(snapshot.guard_allows_live_execution)
        self.assertFalse(snapshot.live_execution_enabled)
        self.assertEqual(snapshot.live_execution_reason, "manual execution guard requires operator submission")


if __name__ == "__main__":
    unittest.main()
