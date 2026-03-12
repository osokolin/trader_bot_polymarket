from __future__ import annotations

from bot.domain.enums import OperatorActionRequestType
from bot.domain.models import OperatorActionRequest
from bot.services.inbox_handlers.base import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
)


class ScannerSummaryHandler(DecisionInboxRequestHandler):
    request_type = OperatorActionRequestType.SCANNER_SUMMARY

    def build_view(self, request: OperatorActionRequest) -> DecisionInboxRequestView:
        return DecisionInboxRequestView(request=request)

    def apply_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        metadata: dict[str, object],
    ) -> InboxHandlerActionOutcome:
        if action != "details":
            raise DecisionInboxError("This request action is not supported.")
        return InboxHandlerActionOutcome(update_request=False, record_action=False)
