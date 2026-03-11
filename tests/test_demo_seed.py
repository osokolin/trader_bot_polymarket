from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.demo.seed import seed_demo_data
from bot.services.analytics import AnalyticsService
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.reporting import ReportingService
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
from bot.ui import OperatorDashboardApp, OperatorDashboardServices


class DemoSeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)

    def test_seed_helper_populates_demo_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection, services = self._build_services(tmp_dir)
            try:
                result = seed_demo_data(self.settings, *services[:7])
                self.assertIn("approved_proposal_id", result)
                self.assertGreaterEqual(result["alert_count"], 1)
                self.assertGreaterEqual(result["saved_view_count"], 2)
            finally:
                connection.close()

    def test_cli_demo_seed_and_ui_export_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                output = self._run_cli("--config-dir", str(self.config_dir), "demo", "seed")
                payload = json.loads(output)
                proposal_id = payload["approved_proposal_id"]
                intent_id = payload["intent_id"]
                self.assertIn("evaluation_id", payload)

                connection, services = self._build_services(tmp_dir)
                try:
                    app = OperatorDashboardApp(
                        OperatorDashboardServices(
                            proposal_service=services[0],
                            execution_service=services[1],
                            notifications_service=services[2],
                            decision_review_service=services[3],
                            execution_evaluation_service=services[4],
                            outcome_analysis_service=services[5],
                            saved_view_service=services[6],
                            reporting_service=services[7],
                        )
                    )
                    _, decision_export = app.render_response(f"/exports/decision-reviews/proposals/{proposal_id}")
                    self.assertIn("Decision Review Export", decision_export)
                    self.assertIn(proposal_id, decision_export)

                    _, evaluation_export = app.render_response(f"/exports/execution-evaluations/intents/{intent_id}")
                    self.assertIn("Execution Evaluation Export", evaluation_export)
                    self.assertIn(intent_id, evaluation_export)

                    _, analysis_export = app.render_response("/exports/outcome-analysis", "scope=outcomes&group_by=market")
                    self.assertIn("Outcome Analysis Export", analysis_export)
                    self.assertIn("&quot;scope&quot;: &quot;outcomes&quot;", analysis_export)
                finally:
                    connection.close()
            finally:
                os.chdir(original_cwd)

    def _build_services(self, tmp_dir: str):
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        proposal_repository = ProposalRepository(connection)
        intent_repository = OrderIntentRepository(connection)
        audit_log = AuditLogService(AuditRepository(connection))
        proposal_service = ProposalLifecycleService(
            proposal_repository,
            audit_log,
            ProposalEngine(),
            probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
        )
        notifications_service = OperatorNotificationsService(
            WatchlistRepository(connection),
            AlertRepository(connection),
            proposal_repository,
            intent_repository,
        )
        execution_service = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            intent_repository,
            audit_log,
            paper_execution_adapter=PaperExecutionAdapter(),
            notifications_service=notifications_service,
        )
        decision_review_service = DecisionReviewService(
            proposal_service,
            execution_service,
            DecisionReviewRepository(connection),
        )
        execution_evaluation_service = ExecutionEvaluationService(
            proposal_service,
            execution_service,
            ExecutionEvaluationRepository(connection),
        )
        outcome_analysis_service = OutcomeAnalysisService(
            proposal_service,
            DecisionReviewRepository(connection),
            ExecutionEvaluationRepository(connection),
            OutcomeAnalysisRepository(connection),
        )
        saved_view_service = SavedViewService(SavedViewRepository(connection))
        reporting_service = ReportingService(
            DecisionReviewRepository(connection),
            execution_evaluation_service,
            outcome_analysis_service,
            notifications_service,
            AnalyticsService(proposal_service, execution_service),
        )
        return connection, (
            proposal_service,
            execution_service,
            notifications_service,
            decision_review_service,
            execution_evaluation_service,
            outcome_analysis_service,
            saved_view_service,
            reporting_service,
        )

    def _run_cli(self, *args: str) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(list(args))
        self.assertEqual(exit_code, 0)
        return buffer.getvalue().strip()
