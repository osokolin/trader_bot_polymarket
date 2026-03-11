from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import IntentStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.analytics import AnalyticsService
from bot.services.audit_log import AuditLogService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, OrderIntentRepository, ProposalRepository
from bot.utils.time import utc_now


class AnalyticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_analytics",
            title="Will CPI cool next print?",
            category="crypto",
            liquidity_usd=20000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear rules",
            rules_confidence=0.96,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_analytics",
            fair_probability=0.67,
            confidence=0.87,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
        )

    def test_aggregate_analytics_and_time_window_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                proposal_service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                execution_service = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                analytics_service = AnalyticsService(proposal_service, execution_service)

                first = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                first_approved = proposal_service.approve(
                    self.settings,
                    first.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                first_intent = execution_service.create_order_intent(first_approved)
                execution_service.prepare_submission(first_intent.intent_id)
                execution_service.simulate_intent(first_intent.intent_id, actor="alice")

                second_market = replace(self.market, market_id="mkt_analytics_2", title="Will ETH outperform BTC?")
                second = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(second_market, self.probability, 0.55),
                )
                second_approved = proposal_service.approve(
                    self.settings,
                    second.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=second_market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                stale_time = utc_now() - timedelta(hours=48)
                stale_proposal = replace(second_approved, updated_at=stale_time)
                ProposalRepository(connection).save(stale_proposal)
                stale_intent = execution_service.create_order_intent(stale_proposal)
                stale_intent = replace(stale_intent, updated_at=stale_time, created_at=stale_time)
                execution_service.order_intent_repository.save(stale_intent)
                execution_service.order_intent_repository.save(replace(stale_intent, status=IntentStatus.PREPARED, updated_at=stale_time))
                old_execution = execution_service.simulate_intent(stale_intent.intent_id, actor="alice")
                saved_execution = execution_service.latest_simulated_execution(stale_intent.intent_id)
                execution_service.order_intent_repository.save_execution(replace(saved_execution, created_at=stale_time))
                stale_terminal = execution_service.latest_intent_state(stale_intent.intent_id)
                execution_service.order_intent_repository.save(replace(stale_terminal, updated_at=stale_time))

                total = analytics_service.summarize("portfolio")
                self.assertEqual(total.active_proposal_count, 2)
                self.assertEqual(total.approved_proposal_count, 2)
                self.assertEqual(total.active_intent_count, 0)
                self.assertEqual(total.terminal_intent_count, 2)
                self.assertEqual(total.simulated_execution_count, 2)
                self.assertGreater(total.total_simulated_filled_size_usd, 0.0)
                self.assertIsNotNone(total.average_simulated_slippage_bps)

                recent = analytics_service.summarize("session", since_hours=24)
                self.assertEqual(recent.active_proposal_count, 1)
                self.assertEqual(recent.approved_proposal_count, 1)
                self.assertEqual(recent.terminal_intent_count, 1)
                self.assertEqual(recent.simulated_execution_count, 1)
                self.assertLess(recent.total_simulated_filled_size_usd, total.total_simulated_filled_size_usd)
                self.assertIsNotNone(old_execution)
            finally:
                connection.close()

    def test_cli_summary_commands_report_metrics_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                proposal_service = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                execution_service = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    OrderIntentRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                )
                proposal = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = proposal_service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="cli",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                intent = execution_service.create_order_intent(approved)
                execution_service.prepare_submission(intent.intent_id)
                execution_service.simulate_intent(intent.intent_id, actor="cli")
            finally:
                connection.close()

            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                portfolio_output = self._run_cli("--config-dir", str(self.config_dir), "portfolio", "summary")
                self.assertIn("analytics_scope: portfolio", portfolio_output)
                self.assertIn("active_proposal_count: 1", portfolio_output)
                self.assertIn("terminal_intent_count: 1", portfolio_output)
                self.assertIn("simulated_execution_count: 1", portfolio_output)

                session_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "session",
                    "summary",
                    "--since-hours",
                    "24",
                )
                self.assertIn("analytics_scope: session", session_output)
                self.assertIn("since_hours: 24", session_output)
                self.assertIn("average_simulated_slippage_bps:", session_output)
            finally:
                os.chdir(original_cwd)

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
