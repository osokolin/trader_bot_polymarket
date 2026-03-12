from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from bot.config.models import Settings
from bot.domain.enums import AlertState, ProposalStatus
from bot.domain.models import OperatorAlert, TradeProposal
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsResult, PolymarketDiagnosticsService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.runtime_safety import build_runtime_safety_snapshot
from bot.services.operator_notifications import OperatorNotificationsService


@dataclass(slots=True)
class TelegramNotification:
    kind: str
    payload: object


@dataclass(slots=True)
class TelegramOperatorService:
    settings: Settings
    profile: str
    execution_adapter: object
    proposal_service: ProposalLifecycleService
    notifications_service: OperatorNotificationsService
    scanner_service: MarketOpportunityScannerService
    diagnostics_service: PolymarketDiagnosticsService
    _primed: bool = False
    _seen_proposal_ids: set[str] = field(default_factory=set)
    _seen_alert_ids: set[str] = field(default_factory=set)
    _last_diagnostics_failure: str | None = None
    _last_diagnostics_check_monotonic: float = 0.0
    diagnostics_poll_interval_seconds: float = 300.0

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

    def list_proposals(self, limit: int = 5) -> list[TradeProposal]:
        return self.proposal_service.list_active_proposals()[:limit]

    def get_proposal_details(self, proposal_id: str) -> TradeProposal:
        return self.proposal_service.latest_proposal_state(proposal_id)

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
                notifications.append(TelegramNotification("draft_proposal", proposal))
                self._seen_proposal_ids.add(proposal.proposal_id)

        for alert in open_alerts:
            if alert.alert_id not in self._seen_alert_ids:
                notifications.append(TelegramNotification("alert", alert))
                self._seen_alert_ids.add(alert.alert_id)

        if diagnostics is not None:
            diagnostics_signature = self._diagnostics_signature(diagnostics)
            if diagnostics_signature is not None and diagnostics_signature != self._last_diagnostics_failure:
                notifications.append(TelegramNotification("diagnostics_failure", diagnostics))
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
