from __future__ import annotations

from pathlib import Path

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


def render_static_ui_pages(output_dir: Path, config_dir: Path, profile: str = "balanced") -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(config_dir, profile=profile)
    database = Database(output_dir / "static_ui.db")
    database.initialize()
    connection = database.connect()
    try:
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
            settings,
            __import__("bot.adapters.polymarket.trading", fromlist=["SemiAutoExecutionAdapter"]).SemiAutoExecutionAdapter(),
            intent_repository,
            audit_log,
            paper_execution_adapter=__import__("bot.adapters.polymarket.trading", fromlist=["PaperExecutionAdapter"]).PaperExecutionAdapter(),
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
        seeded = seed_demo_data(
            settings,
            proposal_service,
            execution_service,
            notifications_service,
            decision_review_service,
            execution_evaluation_service,
            outcome_analysis_service,
            saved_view_service,
        )
        app = OperatorDashboardApp(
            OperatorDashboardServices(
                proposal_service=proposal_service,
                execution_service=execution_service,
                notifications_service=notifications_service,
                decision_review_service=decision_review_service,
                execution_evaluation_service=execution_evaluation_service,
                outcome_analysis_service=outcome_analysis_service,
                saved_view_service=saved_view_service,
                reporting_service=reporting_service,
            )
        )
        pages = {
            "ui-dashboard-home.html": app.render_response("/")[1],
            "ui-proposal-detail.html": app.render_response(f"/proposals/{seeded['approved_proposal_id']}")[1],
            "ui-decision-review.html": app.render_response(f"/decision-reviews/proposals/{seeded['approved_proposal_id']}")[1],
            "ui-outcome-analysis.html": app.render_response("/analysis?scope=outcomes&group_by=market")[1],
        }
        for filename, html in pages.items():
            (output_dir / filename).write_text(html, encoding="utf-8")
        return {name: str(output_dir / name) for name in pages}
    finally:
        connection.close()
