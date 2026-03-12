from __future__ import annotations

from bot.domain.enums import OperatorActionRequestStatus, OperatorActionRequestType
from bot.domain.models import OperatorActionRequest
from bot.services.inbox_handlers.base import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
)
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult, PolymarketDiagnosticsService


class DiagnosticsIssueHandler(DecisionInboxRequestHandler):
    request_type = OperatorActionRequestType.DIAGNOSTICS_ISSUE

    def __init__(self, diagnostics_service: PolymarketDiagnosticsService) -> None:
        self.diagnostics_service = diagnostics_service

    def build_view(self, request: OperatorActionRequest) -> DecisionInboxRequestView:
        diagnostics = self.diagnostics_service.run()
        check = self._diagnostics_check_by_label(diagnostics, request.entity_id)
        return DecisionInboxRequestView(
            request=request,
            diagnostics_label=request.entity_id,
            diagnostics_check=check,
        )

    def apply_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        metadata: dict[str, object],
    ) -> InboxHandlerActionOutcome:
        diagnostics = self.diagnostics_service.run()
        if action == "details":
            return InboxHandlerActionOutcome(
                update_request=False,
                record_action=False,
                diagnostics_result=diagnostics,
            )
        if action != "refresh":
            raise DecisionInboxError("This request action is not supported.")
        check = self._diagnostics_check_by_label(diagnostics, request.entity_id)
        if check.ok:
            return InboxHandlerActionOutcome(
                request_status=OperatorActionRequestStatus.ACTIONED,
                mark_actioned=True,
                summary=f"{request.entity_id}: resolved",
                payload={"label": request.entity_id, "message": "resolved", "ok": True},
                action_payload={"diagnostics_ok": True},
                diagnostics_result=diagnostics,
            )
        return InboxHandlerActionOutcome(
            request_status=OperatorActionRequestStatus.ACKNOWLEDGED,
            summary=f"{request.entity_id}: {check.message}",
            payload={"label": request.entity_id, "message": check.message, "ok": False},
            action_payload={"diagnostics_ok": False},
            diagnostics_result=diagnostics,
        )

    def _diagnostics_check_by_label(
        self,
        diagnostics: PolymarketDiagnosticsResult,
        label: str,
    ) -> DiagnosticCheckResult:
        mapping = {
            "gamma": diagnostics.gamma,
            "clob_rest": diagnostics.clob_rest,
            "websocket": diagnostics.websocket,
            "database": diagnostics.database,
        }
        if label not in mapping:
            raise DecisionInboxError(f"Unknown diagnostics check: {label}")
        return mapping[label]
