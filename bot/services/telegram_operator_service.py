from __future__ import annotations

from dataclasses import dataclass, field
import logging
from time import monotonic

from bot.config.models import Settings
from bot.domain.enums import AlertState, AlertType, ProposalStatus
from bot.domain.models import DecisionReview, OperatorActionRequest, OperatorAlert, TradeProposal
from bot.services.audit_log import AuditLogService
from bot.services.decision_inbox import DecisionInboxActionResult, DecisionInboxRequestView, DecisionInboxService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_preview import ExecutionPreviewService
from bot.services.market_opportunity_alerts import MarketOpportunityAlertScanResult, MarketOpportunityAlertService
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsResult, PolymarketDiagnosticsService
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.services.runtime_safety import build_runtime_safety_snapshot
from bot.services.operator_notifications import OperatorNotificationsService

logger = logging.getLogger(__name__)


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
    execution_preview_service: ExecutionPreviewService
    scanner_service: MarketOpportunityScannerService
    market_opportunity_alert_service: MarketOpportunityAlertService | None
    diagnostics_service: PolymarketDiagnosticsService
    _primed: bool = False
    _seen_proposal_ids: set[str] = field(default_factory=set)
    _seen_alert_ids: set[str] = field(default_factory=set)
    _last_diagnostics_failure: str | None = None
    _last_diagnostics_check_monotonic: float = 0.0
    _last_opportunity_scan_monotonic: float = 0.0
    _last_background_opportunity_scan_monotonic: float = 0.0
    _background_opportunity_scan_in_progress: bool = False
    diagnostics_poll_interval_seconds: float = 300.0
    opportunity_scan_cooldown_seconds: float = 60.0
    background_opportunity_scan_interval_seconds: float | None = None
    opportunity_alert_types: tuple[AlertType, ...] = (
        AlertType.NEW_RELEVANT_MARKET,
        AlertType.HIGH_LIQUIDITY_MARKET,
        AlertType.RESOLVING_SOON_MARKET,
        AlertType.POTENTIAL_CONTEXT_MARKET,
    )

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
        view = self.decision_inbox_service.get_request_view(request.request_id)
        self._log_review_preview_display(view, context="review_next")
        return view

    def get_request_details(self, request_id: str) -> DecisionInboxRequestView:
        view = self.decision_inbox_service.get_request_view(request_id)
        self._log_review_preview_display(view, context="request_details")
        return view

    def refresh_request_preview(self, request_id: str, chat_id: int) -> DecisionInboxRequestView:
        view = self.decision_inbox_service.get_request_view(request_id)
        if view.proposal is None:
            raise ValueError("Execution preview is available only for proposal review requests.")
        now = monotonic()
        self.audit_log.log(
            event_type="review_preview_refresh_requested",
            entity_id=request_id,
            message="Operator requested execution preview refresh from review flow",
            payload={
                "request_id": request_id,
                "proposal_id": view.proposal.proposal_id,
                "chat_id": chat_id,
                "source": "telegram",
                "dry_run": True,
            },
        )
        preview = self.execution_preview_service.preview_proposal(view.proposal.proposal_id)
        refreshed_view = self.decision_inbox_service.get_request_view(request_id)
        event_type = "review_preview_failed" if preview.validation_errors else "review_preview_generated"
        self.audit_log.log(
            event_type=event_type,
            entity_id=request_id,
            message="Execution preview refreshed for review flow",
            payload={
                "request_id": request_id,
                "proposal_id": preview.proposal_id,
                "preview_id": preview.preview_id,
                "status": preview.status.value,
                "warning_count": len(preview.warnings),
                "validation_error_count": len(preview.validation_errors),
                "chat_id": chat_id,
                "source": "telegram",
                "dry_run": preview.dry_run,
                "elapsed_ms": int((monotonic() - now) * 1000),
            },
            created_at=preview.created_at,
        )
        self._log_review_preview_display(refreshed_view, context="preview_refresh")
        return refreshed_view

    def apply_request_action(self, request_id: str, action: str, chat_id: int) -> DecisionInboxActionResult:
        self._log_review_decision_context(request_id, action, chat_id)
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
        primed_this_cycle = False
        diagnostics = None
        if self._should_run_diagnostics_check():
            diagnostics = self.diagnostics_service.run()
        active_proposals = self.proposal_service.list_active_proposals()
        open_alerts = self.notifications_service.list_alerts(state=AlertState.OPEN)

        if not self._primed:
            self._seen_proposal_ids.update(item.proposal_id for item in active_proposals)
            self._seen_alert_ids.update(item.alert_id for item in open_alerts)
            if diagnostics is not None:
                self._last_diagnostics_failure = self._diagnostics_signature(diagnostics)
            self._primed = True
            primed_this_cycle = True
        self._run_background_opportunity_scan_if_due()
        active_proposals = self.proposal_service.list_active_proposals()
        open_alerts = self.notifications_service.list_alerts(state=AlertState.OPEN)

        notifications: list[TelegramNotification] = []
        for proposal in active_proposals:
            if proposal.status == ProposalStatus.PENDING_MANUAL_CONFIRMATION and proposal.proposal_id not in self._seen_proposal_ids:
                request = self.decision_inbox_service.create_proposal_review_request(proposal, source="telegram_poll")
                notifications.append(TelegramNotification("inbox_request", request))
                self._seen_proposal_ids.add(proposal.proposal_id)

        for alert in open_alerts:
            if alert.alert_id not in self._seen_alert_ids:
                request = self.decision_inbox_service.create_alert_request(alert, source="telegram_poll")
                if alert.alert_type in self.opportunity_alert_types:
                    notifications.append(TelegramNotification("alert", alert))
                else:
                    notifications.append(TelegramNotification("inbox_request", request))
                self._seen_alert_ids.add(alert.alert_id)

        if diagnostics is not None and not primed_this_cycle:
            current_requests = self.decision_inbox_service.create_diagnostics_requests(diagnostics, source="telegram_poll")
            diagnostics_signature = self._diagnostics_signature(diagnostics)
            if diagnostics_signature is not None and diagnostics_signature != self._last_diagnostics_failure:
                notifications.extend(TelegramNotification("inbox_request", item) for item in current_requests)
            self._last_diagnostics_failure = diagnostics_signature
        return notifications

    def _log_review_preview_display(self, view: DecisionInboxRequestView, *, context: str) -> None:
        if view.proposal is None or view.execution_preview_context is None:
            return
        payload = {
            "request_id": view.request.request_id,
            "proposal_id": view.proposal.proposal_id,
            "context": context,
            "preview_state": view.execution_preview_context.state.value,
            "hint_level": view.execution_preview_context.hint_level.value,
            "preview_stale": view.execution_preview_context.is_stale,
        }
        self.audit_log.log(
            event_type="review_preview_hint_displayed",
            entity_id=view.request.request_id,
            message="Review preview hint displayed",
            payload=payload,
        )
        latest = view.execution_preview_context.latest_preview
        if latest is None:
            self.audit_log.log(
                event_type="review_preview_missing",
                entity_id=view.request.request_id,
                message="Review preview context is missing",
                payload=payload,
            )
            return
        payload.update(
            {
                "preview_id": latest.preview_id,
                "preview_status": latest.status.value,
                "warning_count": len(latest.warnings),
                "validation_error_count": len(latest.validation_errors),
                "dry_run": latest.dry_run,
            }
        )
        self.audit_log.log(
            event_type="review_preview_displayed",
            entity_id=view.request.request_id,
            message="Review preview context displayed",
            payload=payload,
            created_at=latest.created_at,
        )

    def _log_review_decision_context(self, request_id: str, action: str, chat_id: int) -> None:
        view = self.decision_inbox_service.get_request_view(request_id)
        if view.proposal is None or view.execution_preview_context is None:
            return
        payload = {
            "request_id": request_id,
            "proposal_id": view.proposal.proposal_id,
            "action": action,
            "chat_id": chat_id,
            "source": "telegram",
            "preview_state": view.execution_preview_context.state.value,
            "hint_level": view.execution_preview_context.hint_level.value,
            "preview_stale": view.execution_preview_context.is_stale,
        }
        latest = view.execution_preview_context.latest_preview
        if latest is not None:
            payload.update(
                {
                    "preview_id": latest.preview_id,
                    "preview_status": latest.status.value,
                    "warning_count": len(latest.warnings),
                    "validation_error_count": len(latest.validation_errors),
                }
            )
        self.audit_log.log(
            event_type="review_decision_with_preview_context",
            entity_id=request_id,
            message="Review decision applied with preview context",
            payload=payload,
        )

    def _run_background_opportunity_scan_if_due(self) -> None:
        if self.market_opportunity_alert_service is None:
            return
        if self._background_opportunity_scan_in_progress:
            return
        now = monotonic()
        interval = self._background_scan_interval_seconds()
        if interval < 0:
            return
        if now - self._last_background_opportunity_scan_monotonic < interval:
            return
        self._background_opportunity_scan_in_progress = True
        self._last_background_opportunity_scan_monotonic = now
        try:
            result = self.market_opportunity_alert_service.scan(self.settings)
            logger.info(
                "background opportunity scan complete scanned=%s relevant=%s created=%s warnings=%s",
                result.scanned_count,
                result.relevant_count,
                len(result.created_alerts),
                len(result.warning_messages),
            )
        except Exception as exc:
            logger.warning("background opportunity scan failed error=%s", exc)
        finally:
            self._background_opportunity_scan_in_progress = False

    def _background_scan_interval_seconds(self) -> float:
        if self.background_opportunity_scan_interval_seconds is not None:
            return self.background_opportunity_scan_interval_seconds
        return float(self.settings.market_opportunity_alerts.poll_interval_seconds)

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
