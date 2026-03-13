from __future__ import annotations

from datetime import timedelta

from dataclasses import replace

from bot.domain.enums import AlertSeverity, AlertState, AlertType, ProposalStatus, WatchTargetType
from bot.domain.models import OperatorAlert, WatchlistEntry
from bot.storage.repositories import AlertRepository, OrderIntentRepository, ProposalRepository, WatchlistRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class OperatorNotificationsService:
    VALID_TRANSITIONS = {
        AlertState.OPEN: {AlertState.ACKNOWLEDGED, AlertState.DISMISSED, AlertState.RESOLVED},
        AlertState.ACKNOWLEDGED: {AlertState.DISMISSED, AlertState.RESOLVED},
        AlertState.DISMISSED: set(),
        AlertState.RESOLVED: set(),
    }

    def __init__(
        self,
        watchlist_repository: WatchlistRepository,
        alert_repository: AlertRepository,
        proposal_repository: ProposalRepository,
        order_intent_repository: OrderIntentRepository,
    ) -> None:
        self.watchlist_repository = watchlist_repository
        self.alert_repository = alert_repository
        self.proposal_repository = proposal_repository
        self.order_intent_repository = order_intent_repository

    def add_watch(self, target_type: WatchTargetType, target_id: str, label: str | None = None) -> WatchlistEntry:
        entry = WatchlistEntry(
            watch_id=new_id("watch"),
            target_type=target_type,
            target_id=target_id,
            label=label,
            created_at=utc_now(),
        )
        self.watchlist_repository.save(entry)
        return entry

    def remove_watch(self, target_type: WatchTargetType, target_id: str) -> None:
        self.watchlist_repository.delete(target_type, target_id)

    def list_watchlist(self, target_type: WatchTargetType | None = None) -> list[WatchlistEntry]:
        if target_type is None:
            return self.watchlist_repository.list_all()
        return self.watchlist_repository.list_by_type(target_type)

    def list_alerts(self, watchlist_only: bool = False, state: AlertState | None = None) -> list[OperatorAlert]:
        alerts = self.alert_repository.list_all(state=state)
        if not watchlist_only:
            return alerts
        watch_entries = self.watchlist_repository.list_all()
        return [alert for alert in alerts if self._matches_watchlist(alert, watch_entries)]

    def list_alerts_for_entity(self, entity_type: WatchTargetType, entity_id: str) -> list[OperatorAlert]:
        return self.alert_repository.list_for_entity(entity_type, entity_id)

    def get_alert(self, alert_id: str) -> OperatorAlert:
        alert = self.alert_repository.get(alert_id)
        if alert is None:
            raise ValueError(f"Unknown alert: {alert_id}")
        return alert

    def acknowledge_alert(self, alert_id: str) -> OperatorAlert:
        return self._transition_alert(alert_id, AlertState.ACKNOWLEDGED)

    def dismiss_alert(self, alert_id: str) -> OperatorAlert:
        return self._transition_alert(alert_id, AlertState.DISMISSED)

    def resolve_alert(self, alert_id: str) -> OperatorAlert:
        return self._transition_alert(alert_id, AlertState.RESOLVED)

    def scan(self, ttl_warning_minutes: int = 15) -> list[OperatorAlert]:
        alerts: list[OperatorAlert] = []
        now = utc_now()
        ttl_cutoff = now + timedelta(minutes=ttl_warning_minutes)
        for proposal in self.proposal_repository.list_all():
            if proposal.status == ProposalStatus.PENDING_MANUAL_CONFIRMATION and now < proposal.expires_at <= ttl_cutoff:
                alerts.append(
                    self._create_alert(
                        alert_type=AlertType.PROPOSAL_TTL_NEARING,
                        severity=AlertSeverity.WARNING,
                        entity_type=WatchTargetType.PROPOSAL,
                        entity_id=proposal.proposal_id,
                        related_market_id=proposal.market_id,
                        related_proposal_id=proposal.proposal_id,
                        summary=f"Proposal {proposal.proposal_id} is nearing TTL expiry",
                        payload={"expires_at": proposal.expires_at.isoformat(), "status": proposal.status.value},
                    )
                )
            if proposal.status == ProposalStatus.APPROVED and proposal.expires_at <= now:
                alerts.append(
                    self._create_alert(
                        alert_type=AlertType.APPROVED_PROPOSAL_STALE,
                        severity=AlertSeverity.CRITICAL,
                        entity_type=WatchTargetType.PROPOSAL,
                        entity_id=proposal.proposal_id,
                        related_market_id=proposal.market_id,
                        related_proposal_id=proposal.proposal_id,
                        summary=f"Approved proposal {proposal.proposal_id} has become stale",
                        payload={"expires_at": proposal.expires_at.isoformat(), "status": proposal.status.value},
                    )
                )
        return [alert for alert in alerts if alert is not None]

    def create_superseded_intent_alert(self, intent_id: str, proposal_id: str, market_id: str, superseded_by: str) -> OperatorAlert:
        return self._create_alert(
            alert_type=AlertType.ACTIVE_INTENT_SUPERSEDED,
            severity=AlertSeverity.WARNING,
            entity_type=WatchTargetType.INTENT,
            entity_id=intent_id,
            related_market_id=market_id,
            related_proposal_id=proposal_id,
            summary=f"Active intent {intent_id} was superseded by {superseded_by}",
            payload={"superseded_by_intent_id": superseded_by},
        )

    def create_simulated_execution_alert(
        self,
        intent_id: str,
        proposal_id: str,
        market_id: str,
        execution_id: str,
        status: str,
    ) -> OperatorAlert:
        return self._create_alert(
            alert_type=AlertType.SIMULATED_EXECUTION_RECORDED,
            severity=AlertSeverity.INFO,
            entity_type=WatchTargetType.INTENT,
            entity_id=intent_id,
            related_market_id=market_id,
            related_proposal_id=proposal_id,
            summary=f"New simulated execution {execution_id} recorded for intent {intent_id}",
            payload={"execution_id": execution_id, "status": status},
        )

    def create_market_opportunity_alert(
        self,
        *,
        alert_type: AlertType,
        market_id: str,
        summary: str,
        payload: dict[str, object],
        severity: AlertSeverity = AlertSeverity.INFO,
    ) -> OperatorAlert | None:
        existing = self.alert_repository.find_any_by_type_and_entity(
            alert_type,
            WatchTargetType.MARKET,
            market_id,
        )
        if existing is not None:
            return None
        alert = OperatorAlert(
            alert_id=new_id("alert"),
            alert_type=alert_type,
            severity=severity,
            state=AlertState.OPEN,
            entity_type=WatchTargetType.MARKET,
            entity_id=market_id,
            related_market_id=market_id,
            related_proposal_id=None,
            summary=summary,
            payload=payload,
            created_at=utc_now(),
        )
        self.alert_repository.save(alert)
        return alert

    def _create_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        entity_type: WatchTargetType,
        entity_id: str,
        related_market_id: str | None,
        related_proposal_id: str | None,
        summary: str,
        payload: dict[str, object],
    ) -> OperatorAlert:
        existing = self.alert_repository.find_active_by_type_and_entity(alert_type, entity_type, entity_id)
        if existing is not None:
            return existing
        alert = OperatorAlert(
            alert_id=new_id("alert"),
            alert_type=alert_type,
            severity=severity,
            state=AlertState.OPEN,
            entity_type=entity_type,
            entity_id=entity_id,
            related_market_id=related_market_id,
            related_proposal_id=related_proposal_id,
            summary=summary,
            payload=payload,
            created_at=utc_now(),
        )
        self.alert_repository.save(alert)
        return alert

    def _transition_alert(self, alert_id: str, state: AlertState) -> OperatorAlert:
        alert = self.alert_repository.get(alert_id)
        if alert is None:
            raise ValueError(f"Unknown alert: {alert_id}")
        if state not in self.VALID_TRANSITIONS.get(alert.state, set()):
            raise ValueError(f"Invalid alert transition: {alert.state.value} -> {state.value}")
        now = utc_now()
        updated = replace(
            alert,
            state=state,
            acknowledged_at=now if state == AlertState.ACKNOWLEDGED else alert.acknowledged_at,
            dismissed_at=now if state == AlertState.DISMISSED else alert.dismissed_at,
            resolved_at=now if state == AlertState.RESOLVED else alert.resolved_at,
        )
        self.alert_repository.save(updated)
        return updated

    def _matches_watchlist(self, alert: OperatorAlert, watch_entries: list[WatchlistEntry]) -> bool:
        for entry in watch_entries:
            if entry.target_type == WatchTargetType.MARKET and entry.target_id == alert.related_market_id:
                return True
            if entry.target_type == WatchTargetType.PROPOSAL and (
                entry.target_id == alert.entity_id or entry.target_id == alert.related_proposal_id
            ):
                return True
            if entry.target_type == WatchTargetType.INTENT and entry.target_id == alert.entity_id:
                return True
        return False
