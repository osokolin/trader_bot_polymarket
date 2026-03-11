from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from bot.adapters.polymarket.trading import SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.saved_views import SavedViewService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    OrderIntentRepository,
    OutcomeAnalysisRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
    SavedViewRepository,
    WatchlistRepository,
)
from bot.utils.time import utc_now


class SavedViewsAndReportingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_reporting",
            title="Will CPI cool next print?",
            category="crypto",
            liquidity_usd=22000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear",
            rules_confidence=0.98,
            tags=["macro"],
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id=self.market.market_id,
            fair_probability=0.65,
            confidence=0.82,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
        )

    def test_saved_views_and_export_digest_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._seed_data(tmp_dir)
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                saved = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "views",
                    "save",
                    "--name",
                    "market-outcomes",
                    "--kind",
                    "analysis_outcomes",
                    "--params",
                    "{\"group_by\":\"market\",\"since_hours\":24}",
                )
                self.assertIn("saved_view_count: 1", saved)
                self.assertIn("name=market-outcomes", saved)

                listed = self._run_cli("--config-dir", str(self.config_dir), "views", "list")
                self.assertIn("saved_view_count: 1", listed)
                self.assertIn("market-outcomes", listed)

                run_output = self._run_cli("--config-dir", str(self.config_dir), "views", "run", "market-outcomes")
                self.assertIn("analysis_scope: outcomes", run_output)
                self.assertIn(f"group={self.market.market_id}", run_output)

                review_export = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "export",
                    "decision-review",
                    "--proposal-id",
                    self.proposal_id,
                )
                self.assertIn("\"proposal_id\":", review_export)
                self.assertIn(self.proposal_id, review_export)

                eval_path = Path(tmp_dir) / "execution_eval.json"
                file_export = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "export",
                    "execution-evaluation",
                    "--intent-id",
                    self.intent_id,
                    "--output",
                    str(eval_path),
                )
                self.assertIn("written:", file_export)
                self.assertTrue(eval_path.exists())
                written = json.loads(eval_path.read_text(encoding="utf-8"))
                self.assertEqual(written["intent_id"], self.intent_id)

                analysis_export = self._run_cli(
                    "--config-dir",
                    str(self.config_dir),
                    "export",
                    "outcome-analysis",
                    "--scope",
                    "outcomes",
                    "--group-by",
                    "market",
                )
                self.assertIn("\"scope\": \"outcomes\"", analysis_export)
                self.assertIn(self.market.market_id, analysis_export)

                daily = self._run_cli("--config-dir", str(self.config_dir), "digest", "daily")
                self.assertIn("digest_scope: daily", daily)
                self.assertIn("outcome_analysis_summary:", daily)

                session = self._run_cli("--config-dir", str(self.config_dir), "digest", "session")
                self.assertIn("digest_scope: session", session)
                self.assertIn("alerts_open:", session)
            finally:
                os.chdir(original_cwd)

    def test_invalid_saved_view_definitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = Database(Path(tmp_dir) / "bot.db")
            database.initialize()
            connection = database.connect()
            try:
                service = SavedViewService(SavedViewRepository(connection))
                with self.assertRaisesRegex(ValueError, "Unsupported saved view kind"):
                    service.save("bad-kind", "unknown_kind", {})
                with self.assertRaisesRegex(ValueError, "Missing saved view params"):
                    service.save("missing-required", "analysis_outcomes", {})
                with self.assertRaisesRegex(ValueError, "Invalid saved view param"):
                    service.save("bad-param", "analysis_outcomes", {"group_by": "nope"})
                with self.assertRaisesRegex(ValueError, "Unknown saved view params"):
                    service.save("unknown-param", "alerts_list", {"bogus": True})
            finally:
                connection.close()

    def _seed_data(self, tmp_dir: str) -> None:
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        try:
            proposal_service = ProposalLifecycleService(
                ProposalRepository(connection),
                AuditLogService(AuditRepository(connection)),
                ProposalEngine(),
                probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
            )
            notifications_service = OperatorNotificationsService(
                WatchlistRepository(connection),
                AlertRepository(connection),
                ProposalRepository(connection),
                OrderIntentRepository(connection),
            )
            execution_service = ExecutionPipelineService(
                self.settings,
                SemiAutoExecutionAdapter(),
                OrderIntentRepository(connection),
                AuditLogService(AuditRepository(connection)),
                notifications_service=notifications_service,
            )
            review_service = DecisionReviewService(
                proposal_service,
                execution_service,
                DecisionReviewRepository(connection),
            )
            evaluation_service = ExecutionEvaluationService(
                proposal_service,
                execution_service,
                ExecutionEvaluationRepository(connection),
            )
            analysis_service = OutcomeAnalysisService(
                proposal_service,
                DecisionReviewRepository(connection),
                ExecutionEvaluationRepository(connection),
                OutcomeAnalysisRepository(connection),
            )
            proposal = proposal_service.create(
                self.settings,
                proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
            )
            approved = proposal_service.approve(
                self.settings,
                proposal.proposal_id,
                actor="alice",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                market=self.market,
                probability=self.probability,
                data_age_seconds=0,
            )
            intent = execution_service.create_order_intent(replace(approved, current_size_usd=40.0))
            execution_service.prepare_submission(intent.intent_id)
            execution_service.simulate_intent(intent.intent_id, actor="alice")
            review_service.create_for_proposal(proposal.proposal_id)
            evaluation_service.evaluate_intent(intent.intent_id)
            analysis_service.summarize_outcomes("market")
            self.proposal_id = proposal.proposal_id
            self.intent_id = intent.intent_id
        finally:
            connection.close()

    def _run_cli(self, *argv: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(argv))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
