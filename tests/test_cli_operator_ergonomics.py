from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bot.cli.app import main
from bot.adapters.polymarket.trading import SemiAutoExecutionAdapter
from bot.config.loader import load_settings
from bot.domain.enums import PositionStatus, SourceType
from bot.domain.models import Market, Position, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.execution_pipeline import ExecutionBoundaryError, ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, OrderIntentRepository, PositionRepository, ProposalRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class CliOperatorErgonomicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_cli",
            title="Will the Fed cut rates this quarter?",
            category="crypto",
            liquidity_usd=25000,
            spread_pct=0.02,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear market rules",
            rules_confidence=0.98,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_cli",
            fair_probability=0.68,
            confidence=0.88,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
        )

    def test_cli_lists_and_safety_health_output_include_rich_runtime_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "bot.db"
            database = Database(db_path)
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
                )
                proposal = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                approved = proposal_service.approve(
                    self.settings,
                    proposal.proposal_id,
                    actor="cli-test",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                rejected_source = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.54),
                )
                rejected = proposal_service.reject(rejected_source.proposal_id, actor="cli-test")
                intent = execution_service.create_order_intent(approved)
                execution_service.prepare_submission(intent.intent_id)
                with self.assertRaises(ExecutionBoundaryError):
                    execution_service.submit_intent(intent.intent_id)
                sim_proposal = proposal_service.create(
                    self.settings,
                    proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
                )
                sim_approved = proposal_service.approve(
                    self.settings,
                    sim_proposal.proposal_id,
                    actor="cli-test",
                    open_positions=0,
                    unresolved_exposure_usd=0.0,
                    theme_exposure_usd=0.0,
                    market=self.market,
                    probability=self.probability,
                    data_age_seconds=0,
                )
                simulated_intent = execution_service.create_order_intent(sim_approved)
                execution_service.prepare_submission(simulated_intent.intent_id)
                execution_service.simulate_intent(simulated_intent.intent_id, actor="cli-test")
                PositionRepository(connection).save(
                    Position(
                        position_id=new_id("pos"),
                        market_id=approved.market_id,
                        size_usd=125.0,
                        entry_price=approved.market_price,
                        status=PositionStatus.OPEN,
                        opened_at=utc_now(),
                        theme="macro",
                    )
                )
            finally:
                connection.close()

            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                proposals_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "list",
                    "--scope",
                    "approved",
                    "--limit",
                    "5",
                    "--offset",
                    "0",
                    "--sort",
                    "updated_desc",
                )
                self.assertIn("scope=approved total=2 returned=2 limit=5 offset=0 sort=updated_desc", proposals_output)
                self.assertIn("total_status_summary=approved=2", proposals_output)
                self.assertIn("returned_status_summary=approved=2", proposals_output)
                self.assertIn("policy=-", proposals_output)

                all_proposals_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "list",
                    "--scope",
                    "all",
                    "--limit",
                    "1",
                    "--offset",
                    "0",
                    "--sort",
                    "updated_desc",
                )
                self.assertIn("scope=all total=3 returned=1 limit=1 offset=0 sort=updated_desc", all_proposals_output)
                self.assertIn("total_status_summary=approved=2, cancelled=1", all_proposals_output)
                self.assertIn("returned_status_summary=approved=1", all_proposals_output)

                show_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "show",
                    approved.proposal_id,
                )
                self.assertIn(f"proposal_id: {approved.proposal_id}", show_output)
                self.assertIn("status_help: Passed fresh revalidation", show_output)
                self.assertIn("policy_details:", show_output)
                self.assertIn("risk_points:", show_output)

                rejected_show_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "show",
                    rejected.proposal_id,
                )
                self.assertIn("status: cancelled", rejected_show_output)
                self.assertIn("status_help: No longer actionable", rejected_show_output)

                latest_approved_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "proposals",
                    "latest-approved",
                )
                self.assertIn("latest_approved_proposal:", latest_approved_output)
                self.assertIn("| approved |", latest_approved_output)

                intents_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "list",
                    "--scope",
                    "terminal",
                    "--limit",
                    "10",
                    "--offset",
                    "0",
                    "--sort",
                    "updated_desc",
                )
                self.assertIn("scope=terminal total=2 returned=2 limit=10 offset=0 sort=updated_desc", intents_output)
                self.assertIn("total_status_summary=simulated_filled=1, submission_disabled=1", intents_output)
                self.assertIn("returned_status_summary=simulated_filled=1, submission_disabled=1", intents_output)

                latest_terminal_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "latest-terminal",
                )
                self.assertIn("latest_terminal_intent:", latest_terminal_output)
                self.assertTrue(
                    "submission_disabled" in latest_terminal_output or "simulated_filled" in latest_terminal_output
                )

                intent_show_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "show",
                    intent.intent_id,
                )
                self.assertIn("status_help: Submission path is disabled by the semi_auto execution boundary.", intent_show_output)

                simulated_show_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "show",
                    simulated_intent.intent_id,
                )
                self.assertIn("status: simulated_filled", simulated_show_output)
                self.assertIn("status_help: Paper execution simulated a full fill.", simulated_show_output)

                simulated_exec_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "executions",
                    simulated_intent.intent_id,
                )
                self.assertIn("simulated_execution_count: 1", simulated_exec_output)
                self.assertIn("simulated_execution | execution_id=", simulated_exec_output)
                self.assertIn("reference_price=", simulated_exec_output)
                self.assertIn("best_bid=", simulated_exec_output)
                self.assertIn("best_ask=", simulated_exec_output)
                self.assertIn("slippage_bps=", simulated_exec_output)
                self.assertIn("fill_timestamp=", simulated_exec_output)
                self.assertIn("latency_ms=", simulated_exec_output)

                simulated_timeline_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "timeline",
                    simulated_intent.intent_id,
                )
                self.assertIn("simulated_fill_event_count: 1", simulated_timeline_output)
                self.assertIn("simulated_fill_event | execution_id=", simulated_timeline_output)
                self.assertIn("remaining_size_usd=0.00", simulated_timeline_output)

                simulated_summary_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "simulation-summary",
                    "--intent-id",
                    simulated_intent.intent_id,
                )
                self.assertIn("simulation_scope: intent", simulated_summary_output)
                self.assertIn("execution_count: 1", simulated_summary_output)
                self.assertIn("filled_count: 1", simulated_summary_output)

                overall_summary_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "simulation-summary",
                )
                self.assertIn("simulation_scope: all", overall_summary_output)
                self.assertIn("execution_count: 1", overall_summary_output)
                self.assertIn("total_filled_size_usd: 40.00", overall_summary_output)

                latest_simulated_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "intents",
                    "latest-simulated",
                )
                self.assertIn("simulated_execution_count: 1", latest_simulated_output)
                self.assertIn("status=simulated_filled", latest_simulated_output)

                safety_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "safety",
                    "inspect",
                )
                self.assertIn("mode: semi_auto", safety_output)
                self.assertIn("profile: balanced", safety_output)
                self.assertIn("execution_boundary: semi_auto_strict", safety_output)
                self.assertIn("config_live_execution_enabled: False", safety_output)
                self.assertIn("mode_supports_live_execution: False", safety_output)
                self.assertIn("adapter_supports_live_execution: False", safety_output)
                self.assertIn("guard_allows_live_execution: False", safety_output)
                self.assertIn("live_execution_enabled: False", safety_output)
                self.assertIn("live_execution_reason: config disables live execution", safety_output)

                health_output = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "health",
                    "inspect",
                )
                self.assertIn("semi_auto_strict: True", health_output)
                self.assertIn("unresolved_exposure_usd: 125.00", health_output)
                self.assertIn("unresolved_exposure_remaining_usd:", health_output)
                self.assertIn("bankroll_total_usd:", health_output)
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
