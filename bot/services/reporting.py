from __future__ import annotations

import json
from pathlib import Path

from bot.services.analytics import AnalyticsService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.storage.repositories import DecisionReviewRepository


class ReportingService:
    def __init__(
        self,
        decision_review_repository: DecisionReviewRepository,
        execution_evaluation_service: ExecutionEvaluationService,
        outcome_analysis_service: OutcomeAnalysisService,
        notifications_service: OperatorNotificationsService,
        analytics_service: AnalyticsService,
    ) -> None:
        self.decision_review_repository = decision_review_repository
        self.execution_evaluation_service = execution_evaluation_service
        self.outcome_analysis_service = outcome_analysis_service
        self.notifications_service = notifications_service
        self.analytics_service = analytics_service

    def export_decision_review(self, proposal_id: str) -> dict[str, object]:
        snapshot = self.decision_review_repository.latest_for_proposal(proposal_id)
        if snapshot is None:
            raise ValueError(f"No decision review for proposal: {proposal_id}")
        return {
            "review_id": snapshot.review_id,
            "proposal_id": proposal_id,
            "market_id": snapshot.market_id,
            "probability_snapshot_id": snapshot.probability_snapshot_id,
            "summary": snapshot.summary,
            "payload": snapshot.payload,
        }

    def export_execution_evaluation(self, proposal_id: str | None = None, intent_id: str | None = None) -> dict[str, object]:
        if intent_id is not None:
            evaluation = self.execution_evaluation_service.evaluate_intent(intent_id)
        elif proposal_id is not None:
            evaluation = self.execution_evaluation_service.evaluate_proposal(proposal_id)
        else:
            raise ValueError("export_execution_evaluation requires proposal_id or intent_id")
        return {
            "evaluation_id": evaluation.evaluation_id,
            "proposal_id": evaluation.proposal_id,
            "intent_id": evaluation.intent_id,
            "execution_id": evaluation.execution_id,
            "verdict": evaluation.verdict,
            "summary": evaluation.summary,
        }

    def export_outcome_analysis(self, scope: str, group_by: str, since_hours: int | None = None) -> dict[str, object]:
        snapshot = (
            self.outcome_analysis_service.summarize_outcomes(group_by, since_hours)
            if scope == "outcomes"
            else self.outcome_analysis_service.summarize_learning(group_by, since_hours)
        )
        return {
            "snapshot_id": snapshot.snapshot_id,
            "scope": snapshot.scope,
            "group_by": snapshot.group_by,
            "summary": snapshot.summary,
            "groups": [
                {
                    "group_value": item.group_value,
                    "review_count": item.review_count,
                    "evaluation_count": item.evaluation_count,
                    "verdict_counts": item.verdict_counts,
                }
                for item in snapshot.groups
            ],
        }

    def write_export(self, payload: dict[str, object], output: str | None) -> str:
        content = json.dumps(payload, sort_keys=True, indent=2)
        if output is None:
            return content
        Path(output).write_text(content, encoding="utf-8")
        return f"written: {output}"

    def build_digest(self, scope: str, since_hours: int) -> dict[str, object]:
        analytics = self.analytics_service.summarize(scope, since_hours)
        alerts = self.notifications_service.list_alerts()
        analysis = self.outcome_analysis_service.summarize_outcomes("verdict_type", since_hours)
        return {
            "scope": scope,
            "since_hours": since_hours,
            "alerts_open": sum(1 for item in alerts if item.state.value == "open"),
            "analytics": {
                "active_proposal_count": analytics.active_proposal_count,
                "approved_proposal_count": analytics.approved_proposal_count,
                "active_intent_count": analytics.active_intent_count,
                "terminal_intent_count": analytics.terminal_intent_count,
                "simulated_execution_count": analytics.simulated_execution_count,
            },
            "outcome_analysis_summary": analysis.summary,
            "group_count": len(analysis.groups),
        }
