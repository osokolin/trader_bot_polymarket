from __future__ import annotations

from dataclasses import dataclass, replace

from bot.config.models import Settings
from bot.domain.enums import (
    OperatorActionEntityType,
    OperatorActionRequestStatus,
    OperatorActionRequestType,
)
from bot.domain.models import OperatorActionRequest, OperatorActionRequestRecord, OperatorAlert, TradeProposal
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReview, DecisionReviewService
from bot.services.execution_preview import ExecutionPreviewService
from bot.services.inbox_handlers import (
    DecisionInboxError,
    DecisionInboxRequestHandler,
    DecisionInboxRequestView,
    InboxHandlerActionOutcome,
    build_default_inbox_handlers,
)
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult, PolymarketDiagnosticsService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.repositories import OperatorActionRequestRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


@dataclass(slots=True)
class DecisionInboxActionResult:
    request: OperatorActionRequest
    action: str
    proposal: TradeProposal | None = None
    alert: OperatorAlert | None = None
    decision_review: DecisionReview | None = None
    diagnostics_result: PolymarketDiagnosticsResult | None = None


class DecisionInboxService:
    def __init__(
        self,
        settings: Settings,
        repository: OperatorActionRequestRepository,
        audit_log: AuditLogService,
        proposal_service: ProposalLifecycleService,
        decision_review_service: DecisionReviewService,
        execution_preview_service: ExecutionPreviewService,
        notifications_service: OperatorNotificationsService,
        diagnostics_service: PolymarketDiagnosticsService,
        handlers: dict[OperatorActionRequestType, DecisionInboxRequestHandler] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.audit_log = audit_log
        self.proposal_service = proposal_service
        self.decision_review_service = decision_review_service
        self.execution_preview_service = execution_preview_service
        self.notifications_service = notifications_service
        self.diagnostics_service = diagnostics_service
        self.handlers = handlers or build_default_inbox_handlers(
            settings=settings,
            proposal_service=proposal_service,
            decision_review_service=decision_review_service,
            execution_preview_service=execution_preview_service,
            notifications_service=notifications_service,
            diagnostics_service=diagnostics_service,
        )

    def create_proposal_review_request(self, proposal: TradeProposal, source: str = "system") -> OperatorActionRequest:
        return self._create_or_update_request(
            request_type=OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST,
            entity_type=OperatorActionEntityType.PROPOSAL,
            entity_id=proposal.proposal_id,
            title="Proposal Review Request",
            summary=f"{proposal.market_title} | edge={proposal.edge:+.4f} conf={proposal.confidence:.2f}",
            payload={
                "proposal_id": proposal.proposal_id,
                "market_id": proposal.market_id,
                "market_title": proposal.market_title,
                "market_price": proposal.market_price,
                "fair_probability": proposal.fair_probability,
                "edge": proposal.edge,
                "confidence": proposal.confidence,
                "status": proposal.status.value,
            },
            source=source,
        )

    def create_alert_request(self, alert: OperatorAlert, source: str = "system") -> OperatorActionRequest:
        return self._create_or_update_request(
            request_type=OperatorActionRequestType.ALERT_NOTIFICATION,
            entity_type=OperatorActionEntityType.ALERT,
            entity_id=alert.alert_id,
            title="Alert Notification",
            summary=alert.summary,
            payload={
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "state": alert.state.value,
                "summary": alert.summary,
            },
            source=source,
        )

    def create_diagnostics_requests(
        self,
        diagnostics: PolymarketDiagnosticsResult,
        source: str = "system",
    ) -> list[OperatorActionRequest]:
        requests: list[OperatorActionRequest] = []
        for label, check in self._failing_diagnostics_checks(diagnostics):
            requests.append(
                self._create_or_update_request(
                    request_type=OperatorActionRequestType.DIAGNOSTICS_ISSUE,
                    entity_type=OperatorActionEntityType.DIAGNOSTICS,
                    entity_id=label,
                    title="Diagnostics Issue",
                    summary=f"{label}: {check.message}",
                    payload={"label": label, "message": check.message, "ok": check.ok},
                    source=source,
                )
            )
        return requests

    def list_open_requests(self, limit: int = 10) -> list[OperatorActionRequest]:
        return self.repository.list_by_statuses(list(OperatorActionRequestStatus.active_states()))[:limit]

    def list_review_queue(self, limit: int = 10) -> list[OperatorActionRequest]:
        items = self.repository.list_by_statuses([OperatorActionRequestStatus.OPEN])
        items.sort(key=lambda item: item.created_at)
        return items[:limit]

    def get_next_open_request(self) -> OperatorActionRequest | None:
        items = self.list_review_queue(limit=1)
        return items[0] if items else None

    def get_request(self, request_id: str) -> OperatorActionRequest:
        request = self.repository.get(request_id)
        if request is None:
            raise DecisionInboxError(f"Unknown request: {request_id}")
        return request

    def get_request_view(self, request_id: str) -> DecisionInboxRequestView:
        request = self.get_request(request_id)
        return self._get_handler(request.request_type).build_view(request)

    def apply_action(self, request_id: str, action: str, actor: str, source: str, chat_id: int | None = None) -> DecisionInboxActionResult:
        request = self.get_request(request_id)
        metadata = self._action_metadata(request, action, source, chat_id)
        if action == "skip":
            return self._skip_request(request, actor, metadata)
        outcome = self._get_handler(request.request_type).apply_action(request, action, actor, metadata)
        updated_request = request
        if outcome.update_request:
            updated_request = self._apply_request_outcome(request, actor, outcome)
        if outcome.record_action:
            self._record_action(updated_request, action, actor, "ok", metadata | outcome.action_payload)
        return DecisionInboxActionResult(
            request=updated_request,
            action=action,
            proposal=outcome.proposal,
            alert=outcome.alert,
            decision_review=outcome.decision_review,
            diagnostics_result=outcome.diagnostics_result,
        )

    def _skip_request(
        self,
        request: OperatorActionRequest,
        actor: str,
        metadata: dict[str, object],
    ) -> DecisionInboxActionResult:
        if request.status not in OperatorActionRequestStatus.active_states():
            raise DecisionInboxError("This request can no longer be skipped.")
        updated_request = self._save_request(
            replace(
                request,
                status=OperatorActionRequestStatus.ACKNOWLEDGED,
                updated_at=utc_now(),
            )
        )
        self._record_action(updated_request, "skip", actor, "ok", metadata)
        return DecisionInboxActionResult(request=updated_request, action="skip")

    def _apply_request_outcome(
        self,
        request: OperatorActionRequest,
        actor: str,
        outcome: InboxHandlerActionOutcome,
    ) -> OperatorActionRequest:
        now = utc_now()
        updated = replace(
            request,
            status=outcome.request_status or request.status,
            summary=outcome.summary if outcome.summary is not None else request.summary,
            payload=outcome.payload if outcome.payload is not None else request.payload,
            updated_at=now,
            actioned_at=now if outcome.mark_actioned else request.actioned_at,
            actioned_by=actor if outcome.mark_actioned else request.actioned_by,
        )
        return self._save_request(updated)

    def _get_handler(self, request_type: OperatorActionRequestType) -> DecisionInboxRequestHandler:
        handler = self.handlers.get(request_type)
        if handler is None:
            raise DecisionInboxError(f"Unsupported request type: {request_type.value}")
        return handler

    def _create_or_update_request(
        self,
        request_type: OperatorActionRequestType,
        entity_type: OperatorActionEntityType,
        entity_id: str,
        title: str,
        summary: str,
        payload: dict[str, object],
        source: str,
    ) -> OperatorActionRequest:
        existing = self.repository.find_active_by_type_and_entity(request_type, entity_type, entity_id)
        if existing is not None:
            updated = replace(existing, title=title, summary=summary, payload=payload, updated_at=utc_now())
            return self._save_request(updated)
        created_at = utc_now()
        request = OperatorActionRequest(
            request_id=new_id("req"),
            request_type=request_type,
            entity_type=entity_type,
            entity_id=entity_id,
            status=OperatorActionRequestStatus.OPEN,
            title=title,
            summary=summary,
            payload=payload,
            created_at=created_at,
            updated_at=created_at,
            source=source,
        )
        return self._save_request(request)

    def _save_request(self, request: OperatorActionRequest) -> OperatorActionRequest:
        self.repository.save(request)
        self.audit_log.log(
            "operator_action_request_updated",
            request.request_id,
            f"Decision inbox request {request.status.value}",
            {
                "request_type": request.request_type.value,
                "entity_type": request.entity_type.value,
                "entity_id": request.entity_id,
                "status": request.status.value,
            },
            created_at=request.updated_at,
        )
        return request

    def _record_action(
        self,
        request: OperatorActionRequest,
        action: str,
        actor: str,
        result: str,
        payload: dict[str, object],
    ) -> None:
        now = utc_now()
        self.repository.record_action(
            OperatorActionRequestRecord(
                record_id=new_id("reqact"),
                request_id=request.request_id,
                action=action,
                actor=actor,
                result=result,
                payload=payload,
                created_at=now,
            )
        )
        self.audit_log.log(
            "operator_action_request_actioned",
            request.request_id,
            f"Decision inbox action {action}",
            {"request_id": request.request_id, "entity_id": request.entity_id, "action": action, "result": result, **payload},
            created_at=now,
        )

    def _action_metadata(
        self,
        request: OperatorActionRequest,
        action: str,
        source: str,
        chat_id: int | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "request_id": request.request_id,
            "entity_id": request.entity_id,
            "action": action,
            "source": source,
        }
        if chat_id is not None:
            payload["chat_id"] = chat_id
        return payload

    def _failing_diagnostics_checks(self, diagnostics: PolymarketDiagnosticsResult) -> list[tuple[str, DiagnosticCheckResult]]:
        checks = [
            ("gamma", diagnostics.gamma),
            ("clob_rest", diagnostics.clob_rest),
            ("websocket", diagnostics.websocket),
            ("database", diagnostics.database),
        ]
        return [(label, check) for label, check in checks if not check.ok]
