from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
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


class DemoSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)

    def test_demo_seed_cli_lists_and_ui_home_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "smoke.db"
            env = {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}
            with patch.dict(os.environ, env, clear=False):
                seed_output = self._run_cli("--config-dir", str(self.config_dir), "demo", "seed")
                seed_payload = json.loads(seed_output)
                self.assertIn("approved_proposal_id", seed_payload)

                proposals_output = self._run_cli("--config-dir", str(self.config_dir), "proposals", "list", "--scope", "approved")
                self.assertIn("scope=approved", proposals_output)
                self.assertIn(seed_payload["approved_proposal_id"], proposals_output)

                alerts_output = self._run_cli("--config-dir", str(self.config_dir), "alerts", "list", "--state", "open")
                self.assertIn("alert_count:", alerts_output)

                connection, services = self._build_ui_services(db_path)
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
                    status, home = app.render_response("/")
                    self.assertEqual(status, "200 OK")
                    self.assertIn("Панель оператора", home)
                    self.assertIn(seed_payload["approved_proposal_id"], home)
                    self.assertIn("Последняя симуляция", home)
                finally:
                    connection.close()

    def _build_ui_services(self, db_path: Path):
        database = Database(db_path)
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
