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
from bot.domain.enums import AlertState, AlertType, ProposalStatus, SourceType, WatchTargetType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    OrderIntentRepository,
    ProposalRepository,
    WatchlistRepository,
)
from bot.utils.time import utc_now


class OperatorNotificationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_notify",
            title="Will payrolls beat expectations?",
            category="crypto",
            liquidity_usd=18000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.96,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_notify",
            fair_probability=0.66,
            confidence=0.86,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
        )

    def test_alert_generation_and_watchlist_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                proposal_repository = ProposalRepository(connection)
                intent_repository = OrderIntentRepository(connection)
                notifications = OperatorNotificationsService(
                    WatchlistRepository(connection),
                    AlertRepository(connection),
                    proposal_repository,
                    intent_repository,
                )
                lifecycle = ProposalLifecycleService(
                    proposal_repository,
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                pipeline = ExecutionPipelineService(
                    self.settings,
                    SemiAutoExecutionAdapter(),
                    intent_repository,
                    AuditLogService(AuditRepository(connection)),
                    paper_execution_adapter=PaperExecutionAdapter(),
                    notifications_service=notifications,
                )

                nearing = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                proposal_repository.save(replace(nearing, expires_at=utc_now() + timedelta(minutes=5)))

                stale_market = replace(self.market, market_id="mkt_notify_stale", title="Will inflation reaccelerate?")
                stale = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(stale_market, self.probability, 0.55),
                )
                stale_approved = lifecycle.approve(
                    self.settings,
                    stale.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=stale_market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                proposal_repository.save(
                    replace(stale_approved, expires_at=utc_now() - timedelta(minutes=1), updated_at=utc_now())
                )

                supersede_market = replace(self.market, market_id="mkt_notify_intent", title="Will BTC stay above 90k?")
                supersede_proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(supersede_market, self.probability, 0.55),
                )
                supersede_approved = lifecycle.approve(
                    self.settings,
                    supersede_proposal.proposal_id,
                    actor="alice",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=supersede_market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                first_intent = pipeline.create_order_intent(supersede_approved)
                second_intent = pipeline.create_order_intent(supersede_approved, supersede_existing=True)
                pipeline.prepare_submission(second_intent.intent_id)
                pipeline.simulate_intent(second_intent.intent_id, actor="alice")

                scanned = notifications.scan()
                scanned_again = notifications.scan()
                alert_types = {item.alert_type for item in notifications.list_alerts()}
                self.assertIn(AlertType.PROPOSAL_TTL_NEARING, alert_types)
                self.assertIn(AlertType.APPROVED_PROPOSAL_STALE, alert_types)
                self.assertIn(AlertType.ACTIVE_INTENT_SUPERSEDED, alert_types)
                self.assertIn(AlertType.SIMULATED_EXECUTION_RECORDED, alert_types)
                self.assertGreaterEqual(len(scanned), 2)
                self.assertEqual(len(scanned_again), len(scanned))
                ttl_alerts = [item for item in notifications.list_alerts() if item.alert_type == AlertType.PROPOSAL_TTL_NEARING]
                self.assertEqual(len(ttl_alerts), 1)

                notifications.add_watch(WatchTargetType.MARKET, self.market.market_id, "macro market")
                notifications.add_watch(WatchTargetType.PROPOSAL, stale_approved.proposal_id, "stale proposal")
                watched_alerts = notifications.list_alerts(watchlist_only=True)
                watched_types = {item.alert_type for item in watched_alerts}
                self.assertIn(AlertType.PROPOSAL_TTL_NEARING, watched_types)
                self.assertIn(AlertType.APPROVED_PROPOSAL_STALE, watched_types)
                self.assertNotIn(AlertType.ACTIVE_INTENT_SUPERSEDED, watched_types)
                self.assertNotIn(AlertType.SIMULATED_EXECUTION_RECORDED, watched_types)
                self.assertEqual(first_intent.proposal_id, second_intent.proposal_id)
                self.assertEqual(proposal_repository.get(stale_approved.proposal_id).status, ProposalStatus.APPROVED)
                ttl_alert = next(item for item in notifications.list_alerts() if item.alert_type == AlertType.PROPOSAL_TTL_NEARING)
                self.assertEqual(ttl_alert.state, AlertState.OPEN)
                acknowledged = notifications.acknowledge_alert(ttl_alert.alert_id)
                self.assertEqual(acknowledged.state, AlertState.ACKNOWLEDGED)
                with self.assertRaisesRegex(ValueError, "Invalid alert transition"):
                    notifications.acknowledge_alert(ttl_alert.alert_id)
                resolved = notifications.resolve_alert(ttl_alert.alert_id)
                self.assertEqual(resolved.state, AlertState.RESOLVED)
                self.assertEqual(len(notifications.list_alerts(state=AlertState.RESOLVED)), 1)
                with self.assertRaisesRegex(ValueError, "Invalid alert transition"):
                    notifications.dismiss_alert(ttl_alert.alert_id)
            finally:
                connection.close()

    def test_cli_watchlist_and_alert_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                lifecycle = ProposalLifecycleService(
                    ProposalRepository(connection),
                    AuditLogService(AuditRepository(connection)),
                    ProposalEngine(),
                )
                proposal = lifecycle.create(
                    self.settings,
                    lifecycle.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                ProposalRepository(connection).save(
                    replace(proposal, expires_at=utc_now() + timedelta(minutes=5), updated_at=utc_now())
                )
            finally:
                connection.close()

            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                add_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "watchlist",
                    "add",
                    "--type",
                    "market",
                    "--id",
                    self.market.market_id,
                    "--label",
                    "macro watch",
                )
                self.assertIn("watchlist_count: 1", add_output)
                self.assertIn("type=market", add_output)

                list_output = self._run_cli("--config-dir", str(self.config_dir), "watchlist", "list")
                self.assertIn("watchlist_count: 1", list_output)
                self.assertIn(self.market.market_id, list_output)

                scan_output = self._run_cli("--config-dir", str(self.config_dir), "alerts", "scan")
                self.assertIn("alert_count: 1", scan_output)
                self.assertIn("proposal_ttl_nearing", scan_output)

                watched_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "alerts",
                    "list",
                    "--watchlist-only",
                )
                self.assertIn("alert_count: 1", watched_output)
                self.assertIn("proposal_ttl_nearing", watched_output)

                listed = self._run_cli("--config-dir", str(self.config_dir), "alerts", "list", "--state", "open")
                alert_line = next(line for line in listed.splitlines() if " | alert | " in line)
                alert_id = alert_line.split("id=")[1].split(" | ")[0]
                ack_output = self._run_cli("--config-dir", str(self.config_dir), "alerts", "acknowledge", alert_id)
                self.assertIn("state=acknowledged", ack_output)
                resolve_output = self._run_cli("--config-dir", str(self.config_dir), "alerts", "resolve", alert_id)
                self.assertIn("state=resolved", resolve_output)
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
