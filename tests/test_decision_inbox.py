from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from bot.config.loader import load_settings
from bot.domain.enums import (
    AlertSeverity,
    AlertState,
    AlertType,
    OperatorActionRequestStatus,
    OperatorActionRequestType,
    SourceType,
    WatchTargetType,
)
from bot.domain.models import Market, OperatorAlert, ProbabilityEstimate
from bot.services.audit_log import AuditLogService
from bot.services.decision_inbox import DecisionInboxService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult
from bot.services.market_data import RevalidationSnapshot
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    DecisionReviewRepository,
    OperatorActionRequestRepository,
    OrderIntentRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
    WatchlistRepository,
)
from bot.utils.time import utc_now


class _FakeExecutionAdapter:
    supports_live_execution = False


class _FakeSnapshotProvider:
    def __init__(self, market: Market, probability: ProbabilityEstimate, current_price: float) -> None:
        self.market = market
        self.probability = probability
        self.current_price = current_price

    def get_snapshot(self, proposal) -> RevalidationSnapshot:
        return RevalidationSnapshot(
            market=self.market,
            probability=self.probability,
            orderbook=None,
            current_price=self.current_price,
            data_age_seconds=2,
        )


class _FakeDiagnosticsService:
    def __init__(self) -> None:
        self.result = PolymarketDiagnosticsResult(
            gamma=DiagnosticCheckResult(False, "timeout"),
            clob_rest=DiagnosticCheckResult(True, "reachable"),
            websocket=DiagnosticCheckResult(True, "reachable"),
            database=DiagnosticCheckResult(True, "sqlite ready"),
            overall_ok=False,
        )

    def run(self) -> PolymarketDiagnosticsResult:
        return self.result


class DecisionInboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        self.addCleanup(lambda: os.path.exists(temp_db.name) and os.unlink(temp_db.name))
        database = Database(Path(temp_db.name))
        database.initialize()
        self.connection = database.connect()
        self.addCleanup(self.connection.close)
        self.proposal_repository = ProposalRepository(self.connection)
        self.audit_repository = AuditRepository(self.connection)
        self.alert_repository = AlertRepository(self.connection)
        self.notifications_service = OperatorNotificationsService(
            WatchlistRepository(self.connection),
            self.alert_repository,
            self.proposal_repository,
            OrderIntentRepository(self.connection),
        )
        self.market = Market(
            market_id="mkt_1",
            title="Inflation above 4% by Dec 2026",
            category="crypto",
            liquidity_usd=142000.0,
            spread_pct=0.01,
            resolution_time=utc_now() + timedelta(days=7),
            rules_text="Clear",
            rules_confidence=0.95,
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_1",
            fair_probability=0.61,
            confidence=0.72,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )
        self.proposal_service = ProposalLifecycleService(
            self.proposal_repository,
            AuditLogService(self.audit_repository),
            ProposalEngine(),
            snapshot_provider=_FakeSnapshotProvider(self.market, self.probability, current_price=0.49),
            probability_snapshot_repository=ProbabilitySnapshotRepository(self.connection),
        )
        self.execution_service = ExecutionPipelineService(
            self.settings,
            _FakeExecutionAdapter(),
            OrderIntentRepository(self.connection),
            AuditLogService(self.audit_repository),
        )
        self.decision_review_service = DecisionReviewService(
            self.proposal_service,
            self.execution_service,
            DecisionReviewRepository(self.connection),
        )
        self.diagnostics_service = _FakeDiagnosticsService()
        self.repository = OperatorActionRequestRepository(self.connection)
        self.service = DecisionInboxService(
            settings=self.settings,
            repository=self.repository,
            audit_log=AuditLogService(self.audit_repository),
            proposal_service=self.proposal_service,
            decision_review_service=self.decision_review_service,
            notifications_service=self.notifications_service,
            diagnostics_service=self.diagnostics_service,
        )

    def _create_proposal(self):
        context = self.proposal_service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.49)
        return self.proposal_service.create(self.settings, context)

    def test_create_and_list_open_request(self) -> None:
        proposal = self._create_proposal()
        request = self.service.create_proposal_review_request(proposal)
        listed = self.service.list_open_requests()
        self.assertEqual(listed[0].request_id, request.request_id)
        self.assertEqual(listed[0].status, OperatorActionRequestStatus.OPEN)

    def test_get_request_by_id(self) -> None:
        proposal = self._create_proposal()
        request = self.service.create_proposal_review_request(proposal)
        loaded = self.service.get_request(request.request_id)
        self.assertEqual(loaded.entity_id, proposal.proposal_id)
        self.assertEqual(loaded.request_type, OperatorActionRequestType.PROPOSAL_REVIEW_REQUEST)

    def test_request_status_transition_to_actioned_on_approve(self) -> None:
        proposal = self._create_proposal()
        request = self.service.create_proposal_review_request(proposal)
        result = self.service.apply_action(request.request_id, "approve", actor="telegram", source="telegram", chat_id=777)
        self.assertEqual(result.request.status, OperatorActionRequestStatus.ACTIONED)
        actions = self.repository.list_actions(request.request_id)
        self.assertEqual(actions[0].action, "approve")
        self.assertEqual(actions[0].payload["chat_id"], 777)

    def test_alert_acknowledge_routes_and_action_is_recorded(self) -> None:
        alert = OperatorAlert(
            alert_id="alert_1",
            alert_type=AlertType.PROPOSAL_TTL_NEARING,
            severity=AlertSeverity.WARNING,
            state=AlertState.OPEN,
            entity_type=WatchTargetType.PROPOSAL,
            entity_id="proposal_1",
            related_market_id="mkt_1",
            related_proposal_id="proposal_1",
            summary="Proposal nearing TTL expiry",
            payload={},
            created_at=utc_now(),
        )
        self.alert_repository.save(alert)
        request = self.service.create_alert_request(alert)
        result = self.service.apply_action(request.request_id, "acknowledge", actor="telegram", source="telegram", chat_id=123)
        self.assertEqual(result.request.status, OperatorActionRequestStatus.ACTIONED)
        self.assertEqual(result.alert.state, AlertState.ACKNOWLEDGED)

    def test_diagnostics_request_refresh_updates_request(self) -> None:
        requests = self.service.create_diagnostics_requests(self.diagnostics_service.run())
        self.assertEqual(len(requests), 1)
        refreshed = self.service.apply_action(requests[0].request_id, "refresh", actor="telegram", source="telegram", chat_id=555)
        self.assertEqual(refreshed.request.status, OperatorActionRequestStatus.ACKNOWLEDGED)
        self.assertIn("timeout", refreshed.request.summary)

    def test_invalid_request_action_is_rejected(self) -> None:
        proposal = self._create_proposal()
        request = self.service.create_proposal_review_request(proposal)
        with self.assertRaises(ValueError):
            self.service.apply_action(request.request_id, "acknowledge", actor="telegram", source="telegram", chat_id=1)


if __name__ == "__main__":
    unittest.main()
