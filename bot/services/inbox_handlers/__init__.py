from __future__ import annotations

from bot.config.models import Settings
from bot.domain.enums import OperatorActionRequestType
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_preview import ExecutionPreviewService
from bot.services.inbox_handlers.alerts import AlertNotificationHandler
from bot.services.inbox_handlers.base import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
)
from bot.services.inbox_handlers.diagnostics import DiagnosticsIssueHandler
from bot.services.inbox_handlers.proposal_review import ProposalReviewRequestHandler
from bot.services.inbox_handlers.scanner_summary import ScannerSummaryHandler
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsService
from bot.services.proposal_lifecycle import ProposalLifecycleService


def build_default_inbox_handlers(
    settings: Settings,
    proposal_service: ProposalLifecycleService,
    decision_review_service: DecisionReviewService,
    execution_preview_service: ExecutionPreviewService,
    notifications_service: OperatorNotificationsService,
    diagnostics_service: PolymarketDiagnosticsService,
) -> dict[OperatorActionRequestType, DecisionInboxRequestHandler]:
    return {
        OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST: ProposalReviewRequestHandler(
            settings=settings,
            proposal_service=proposal_service,
            decision_review_service=decision_review_service,
            execution_preview_service=execution_preview_service,
        ),
        OperatorActionRequestType.ALERT_NOTIFICATION: AlertNotificationHandler(
            notifications_service=notifications_service,
        ),
        OperatorActionRequestType.DIAGNOSTICS_ISSUE: DiagnosticsIssueHandler(
            diagnostics_service=diagnostics_service,
        ),
        OperatorActionRequestType.SCANNER_SUMMARY: ScannerSummaryHandler(),
    }


__all__ = [
    "DecisionInboxError",
    "DecisionInboxRequestHandler",
    "DecisionInboxRequestView",
    "InboxHandlerActionOutcome",
    "build_default_inbox_handlers",
]
