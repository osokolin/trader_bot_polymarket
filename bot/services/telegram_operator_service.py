from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from bot.config.models import Settings
from bot.domain.enums import AlertState, ProposalStatus
from bot.domain.models import DecisionReview, OperatorActionRequest, OperatorAlert, TradeProposal
from bot.services.audit_log import AuditLogService
from bot.services.decision_inbox import DecisionInboxActionResult, DecisionInboxRequestView, DecisionInboxService
from bot.services.decision_review import DecisionReviewService
from bot.services.market_opportunity_alerts import MarketOpportunityAlertScanResult, MarketOpportunityAlertService
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsResult, PolymarketDiagnosticsService
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.services.runtime_safety import build_runtime_safety_snapshot
from bot.services.operator_notifications import OperatorNotificationsService


@dataclass(slots=True)
class TelegramNotification:
    kind: str
    payload: object


@dataclass(slots=True)
class TelegramProposalAnalysis:
    proposal: TradeProposal
    decision_review: DecisionReview
    scanner_rationale: str


class TelegramCooldownError(RuntimeError):
    pass


@dataclass(slots=True)
class TelegramOperatorService:
    settings: Settings
    profile: str
    execution_adapter: object
    audit_log: AuditLogService
    proposal_service: ProposalLifecycleService
    decision_review_service: DecisionReviewService
    decision_inbox_service: DecisionInboxService
    notifications_service: OperatorNotificationsService
    scanner_service: MarketOpportunityScannerService
    market_opportunity_alert_service: MarketOpportunityAlertService | None
    diagnostics_service: PolymarketDiagnosticsService
    _primed: bool = False
    _seen_proposal_ids: set[str] = field(default_factory=set)
    _seen_alert_ids: set[str] = field(default_factory=set)
    _last_diagnostics_failure: str | None = None
    _last_diagnostics_check_monotonic: float = 0.0
    _last_opportunity_scan_monotonic: float = 0.0
    diagnostics_poll_interval_seconds: float = 300.0
    opportunity_scan_cooldown_seconds: float = 60.0

    def get_status(self) -> dict[str, object]:
        safety = build_runtime_safety_snapshot(
            self.settings,
            self.profile,
            self.execution_adapter,  # type: ignore[arg-type]
            open_positions=0,
            unresolved_exposure_usd=0.0,
        )
        active_proposals = self.proposal_service.list_active_proposals()
        open_alerts = self.notifications_service.list_alerts(state=AlertState.OPEN)
        return {
            "mode": self.settings.mode.value,
            "profile": self.profile,
            "live_execution_enabled": safety.live_execution_enabled,
            "live_execution_reason": safety.live_execution_reason,
            "active_proposals": len(active_proposals),
            "open_alerts": len(open_alerts),
            "semi_auto_strict": safety.semi_auto_strict,
        }

    def get_diagnostics(self) -> PolymarketDiagnosticsResult:
        return self.diagnostics_service.run()

    def get_scanner_results(self, limit: int = 5):
        return self.scanner_service.scan(self.settings, limit=limit)

    def scan_opportunities(self, chat_id: int, limit: int = 200) -> MarketOpportunityAlertScanResult:
        if self.market_opportunity_alert_service is None:
            raise RuntimeError("Opportunity alerts are unavailable.")
        now = monotonic()
        remaining = self.opportunity_scan_cooldown_seconds - (now - self._last_opportunity_scan_monotonic)
        if remaining > 0:
            raise TelegramCooldownError(
                f"Opportunity scan is cooling down. Try again in {int(remaining) + 1}s."
            )
        self._last_opportunity_scan_monotonic = now
        result = self.market_opportunity_alert_service.scan(self.settings, limit=limit)
        self.audit_log.log(
            event_type="telegram_opportunity_scan",
            entity_id=f"chat:{chat_id}",
            message="Telegram operator triggered opportunity alert scan",
            payload={
                "source": "telegram",
                "chat_id": chat_id,
                "limit": limit,
                "scanned_count": result.scanned_count,
                "relevant_count": result.relevant_count,
                "created_alert_count": len(result.created_alerts),
            },
        )
        return result

    def list_proposals(self, limit: int = 5) -> list[TradeProposal]:
        return self.proposal_service.list_active_proposals()[:limit]

    def get_proposal_details(self, proposal_id: str) -> TradeProposal:
        return self.proposal_service.latest_proposal_state(proposal_id)

    def list_inbox(self, limit: int = 10) -> list[OperatorActionRequest]:
        return self.decision_inbox_service.list_open_requests(limit=limit)

    def list_review_queue(self, limit: int = 10) -> list[OperatorActionRequest]:
        return self.decision_inbox_service.list_review_queue(limit=limit)

    def get_next_review_request(self) -> DecisionInboxRequestView | None:
        request = self.decision_inbox_service.get_next_open_request()
        if request is None:
            return None
        return self.decision_inbox_service.get_request_view(request.request_id)

    def get_request_details(self, request_id: str) -> DecisionInboxRequestView:
        return self.decision_inbox_service.get_request_view(request_id)

    def apply_request_action(self, request_id: str, action: str, chat_id: int) -> DecisionInboxActionResult:
        try:
            return self.decision_inbox_service.apply_action(
                request_id=request_id,
                action=action,
                actor="telegram",
                source="telegram",
                chat_id=chat_id,
            )
        except ProposalLifecycleError as exc:
            raise ProposalLifecycleError(self._friendly_transition_message(action, exc)) from exc

    def apply_request_action_and_get_next(
        self,
        request_id: str,
        action: str,
        chat_id: int,
    ) -> tuple[DecisionInboxActionResult, DecisionInboxRequestView | None]:
        result = self.apply_request_action(request_id, action, chat_id)
        next_request = self.get_next_review_request()
        if next_request is not None and next_request.request.request_id == request_id:
            next_request = None
        return result, next_request

    def approve_proposal(self, proposal_id: str, chat_id: int) -> TradeProposal:
        try:
            return self.proposal_service.approve(
                self.settings,
                proposal_id,
                actor="telegram",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
                metadata=self._telegram_metadata(chat_id, proposal_id, "approve"),
            )
        except ProposalLifecycleError as exc:
            raise ProposalLifecycleError(self._friendly_transition_message("approve", exc)) from exc

    def reject_proposal(self, proposal_id: str, chat_id: int) -> TradeProposal:
        try:
            return self.proposal_service.reject(
                proposal_id,
                actor="telegram",
                metadata=self._telegram_metadata(chat_id, proposal_id, "reject"),
            )
        except ProposalLifecycleError as exc:
            raise ProposalLifecycleError(self._friendly_transition_message("reject", exc)) from exc

    def cancel_proposal(self, proposal_id: str, chat_id: int) -> TradeProposal:
        try:
            return self.proposal_service.cancel(
                proposal_id,
                actor="telegram",
                metadata=self._telegram_metadata(chat_id, proposal_id, "cancel"),
            )
        except ProposalLifecycleError as exc:
            raise ProposalLifecycleError(self._friendly_transition_message("cancel", exc)) from exc

    def request_additional_analysis(self, proposal_id: str, chat_id: int) -> TelegramProposalAnalysis:
        proposal = self.proposal_service.request_additional_analysis(
            proposal_id,
            actor="telegram",
            metadata=self._telegram_metadata(chat_id, proposal_id, "analysis"),
        )
        try:
            decision_review = self.decision_review_service.create_for_proposal(proposal_id)
        except Exception as exc:
            raise ProposalLifecycleError(f"Additional analysis unavailable: {exc}") from exc
        scanner_rationale = proposal.thesis[0] if proposal.thesis else "No scanner rationale recorded."
        return TelegramProposalAnalysis(
            proposal=proposal,
            decision_review=decision_review,
            scanner_rationale=scanner_rationale,
        )

    def list_alerts(self, limit: int = 5) -> list[OperatorAlert]:
        return self.notifications_service.list_alerts(state=AlertState.OPEN)[:limit]

    def poll_notifications(self) -> list[TelegramNotification]:
        active_proposals = self.proposal_service.list_active_proposals()
        open_alerts = self.notifications_service.list_alerts(state=AlertState.OPEN)
        diagnostics = None
        if self._should_run_diagnostics_check():
            diagnostics = self.diagnostics_service.run()

        if not self._primed:
            self._seen_proposal_ids.update(item.proposal_id for item in active_proposals)
            self._seen_alert_ids.update(item.alert_id for item in open_alerts)
            if diagnostics is not None:
                self._last_diagnostics_failure = self._diagnostics_signature(diagnostics)
            self._primed = True
            return []

        notifications: list[TelegramNotification] = []
        for proposal in active_proposals:
            if proposal.status == ProposalStatus.PENDING_MANUAL_CONFIRMATION and proposal.proposal_id not in self._seen_proposal_ids:
                request = self.decision_inbox_service.create_proposal_review_request(proposal, source="telegram_poll")
                notifications.append(TelegramNotification("inbox_request", request))
                self._seen_proposal_ids.add(proposal.proposal_id)

        for alert in open_alerts:
            if alert.alert_id not in self._seen_alert_ids:
                request = self.decision_inbox_service.create_alert_request(alert, source="telegram_poll")
                notifications.append(TelegramNotification("inbox_request", request))
                self._seen_alert_ids.add(alert.alert_id)

        if diagnostics is not None:
            current_requests = self.decision_inbox_service.create_diagnostics_requests(diagnostics, source="telegram_poll")
            diagnostics_signature = self._diagnostics_signature(diagnostics)
            if diagnostics_signature is not None and diagnostics_signature != self._last_diagnostics_failure:
                notifications.extend(TelegramNotification("inbox_request", item) for item in current_requests)
            self._last_diagnostics_failure = diagnostics_signature
        return notifications

    def _diagnostics_signature(self, diagnostics: PolymarketDiagnosticsResult) -> str | None:
        if diagnostics.overall_ok:
            return None
        return "|".join(
            [
                diagnostics.gamma.message if not diagnostics.gamma.ok else "",
                diagnostics.clob_rest.message if not diagnostics.clob_rest.ok else "",
                diagnostics.websocket.message if not diagnostics.websocket.ok else "",
                diagnostics.database.message if not diagnostics.database.ok else "",
            ]
        )

    def _should_run_diagnostics_check(self) -> bool:
        now = monotonic()
        if now - self._last_diagnostics_check_monotonic < self.diagnostics_poll_interval_seconds:
            return False
        self._last_diagnostics_check_monotonic = now
        return True

    def _telegram_metadata(self, chat_id: int, proposal_id: str, action: str) -> dict[str, object]:
        return {
            "source": "telegram",
            "chat_id": chat_id,
            "proposal_id": proposal_id,
            "action": action,
        }

    def _friendly_transition_message(self, action: str, exc: ProposalLifecycleError) -> str:
        lower_message = str(exc).lower()
        if "ttl expired" in lower_message or "only pending" in lower_message or "only pending or approved" in lower_message:
            verb = {
                "approve": "approved",
                "reject": "rejected",
                "cancel": "cancelled",
            }.get(action, action)
            return f"This proposal can no longer be {verb}."
        return str(exc)
