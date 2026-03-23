from __future__ import annotations

from bot.config.models import Settings
from bot.domain.enums import OperatorActionRequestStatus, OperatorActionRequestType
from bot.domain.models import OperatorActionRequest
from bot.services.decision_review import DecisionReviewService
from bot.services.inbox_handlers.base import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
)
from bot.services.execution_preview import ExecutionPreviewService
from bot.services.proposal_lifecycle import ProposalLifecycleService


class ProposalReviewRequestHandler(DecisionInboxRequestHandler):
    request_type = OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST

    def __init__(
        self,
        settings: Settings,
        proposal_service: ProposalLifecycleService,
        decision_review_service: DecisionReviewService,
        execution_preview_service: ExecutionPreviewService,
    ) -> None:
        self.settings = settings
        self.proposal_service = proposal_service
        self.decision_review_service = decision_review_service
        self.execution_preview_service = execution_preview_service

    def build_view(self, request: OperatorActionRequest) -> DecisionInboxRequestView:
        proposal = self.proposal_service.latest_proposal_state(request.entity_id)
        return DecisionInboxRequestView(
            request=request,
            proposal=proposal,
            execution_preview_context=self.execution_preview_service.build_review_context(proposal),
        )

    def apply_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        metadata: dict[str, object],
    ) -> InboxHandlerActionOutcome:
        proposal_id = request.entity_id
        if action == "approve":
            proposal = self.proposal_service.approve(
                self.settings,
                proposal_id,
                actor=actor,
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                metadata=metadata,
            )
            return InboxHandlerActionOutcome(
                request_status=OperatorActionRequestStatus.ACTIONED,
                mark_actioned=True,
                proposal=proposal,
            )
        if action == "reject":
            proposal = self.proposal_service.reject(proposal_id, actor=actor, metadata=metadata)
            return InboxHandlerActionOutcome(
                request_status=OperatorActionRequestStatus.ACTIONED,
                mark_actioned=True,
                proposal=proposal,
            )
        if action == "cancel":
            proposal = self.proposal_service.cancel(proposal_id, actor=actor, metadata=metadata)
            return InboxHandlerActionOutcome(
                request_status=OperatorActionRequestStatus.ACTIONED,
                mark_actioned=True,
                proposal=proposal,
            )
        if action == "analysis":
            proposal = self.proposal_service.request_additional_analysis(proposal_id, actor=actor, metadata=metadata)
            return InboxHandlerActionOutcome(
                request_status=OperatorActionRequestStatus.ACKNOWLEDGED,
                proposal=proposal,
                decision_review=self.decision_review_service.create_for_proposal(proposal_id),
            )
        if action == "details":
            return InboxHandlerActionOutcome(
                update_request=False,
                record_action=False,
                proposal=self.proposal_service.latest_proposal_state(proposal_id),
            )
        raise DecisionInboxError(f"Invalid request action: {action}")
