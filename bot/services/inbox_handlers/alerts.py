from __future__ import annotations

from bot.domain.enums import OperatorActionRequestStatus, OperatorActionRequestType
from bot.domain.models import OperatorActionRequest
from bot.services.inbox_handlers.base import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
)
from bot.services.operator_notifications import OperatorNotificationsService


class AlertNotificationHandler(DecisionInboxRequestHandler):
    request_type = OperatorActionRequestType.ALERT_NOTIFICATION

    def __init__(self, notifications_service: OperatorNotificationsService) -> None:
        self.notifications_service = notifications_service

    def build_view(self, request: OperatorActionRequest) -> DecisionInboxRequestView:
        return DecisionInboxRequestView(
            request=request,
            alert=self.notifications_service.get_alert(request.entity_id),
        )

    def apply_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        metadata: dict[str, object],
    ) -> InboxHandlerActionOutcome:
        if action == "details":
            return InboxHandlerActionOutcome(
                update_request=False,
                record_action=False,
                alert=self.notifications_service.get_alert(request.entity_id),
            )
        if action != "acknowledge":
            raise DecisionInboxError("This request action is not supported.")
        return InboxHandlerActionOutcome(
            request_status=OperatorActionRequestStatus.ACTIONED,
            mark_actioned=True,
            alert=self.notifications_service.acknowledge_alert(request.entity_id),
        )
