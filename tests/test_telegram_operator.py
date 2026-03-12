from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import AlertSeverity, AlertState, AlertType, ProposalStatus, SourceType, TradeAction, WatchTargetType
from bot.domain.models import Market, OperatorAlert, OpportunityCandidate, ProbabilityEstimate, TradeProposal
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.market_data import RevalidationSnapshot
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult
from bot.services.telegram_operator_service import TelegramNotification, TelegramOperatorService
from bot.storage.db import Database
from bot.storage.repositories import (
    AuditRepository,
    DecisionReviewRepository,
    OrderIntentRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
)
from bot.telegram import formatter
from bot.telegram.auth import TelegramOperatorAuth
from bot.telegram.bot_app import TelegramBotApp
from bot.telegram.router import TelegramRouter
from bot.utils.time import utc_now


class _FakeExecutionAdapter:
    supports_live_execution = False

    def __init__(self) -> None:
        self.submit_calls = 0

    def submit_order(self, *args, **kwargs):
        self.submit_calls += 1
        raise AssertionError("submit_order must not be called from Telegram proposal actions")


class _FakeTelegramOperatorService:
    def __init__(self) -> None:
        self.fail_scan = False
        self.notifications = []
        self.approved: list[tuple[str, int]] = []
        self.rejected: list[tuple[str, int]] = []
        self.cancelled: list[tuple[str, int]] = []
        self.analysis_requested: list[tuple[str, int]] = []

    def get_status(self):
        return {
            "mode": "semi_auto",
            "profile": "balanced",
            "live_execution_enabled": False,
            "live_execution_reason": "config disables live execution",
            "active_proposals": 4,
            "open_alerts": 1,
            "semi_auto_strict": True,
        }

    def get_diagnostics(self):
        return PolymarketDiagnosticsResult(
            gamma=DiagnosticCheckResult(True, "reachable"),
            clob_rest=DiagnosticCheckResult(True, "reachable"),
            websocket=DiagnosticCheckResult(False, "timeout"),
            database=DiagnosticCheckResult(True, "sqlite ready"),
            overall_ok=False,
        )

    def get_scanner_results(self, limit: int = 5):
        if self.fail_scan:
            raise RuntimeError("scanner unavailable")
        return type(
            "ScanResult",
            (),
            {
                "opportunities": [
                    OpportunityCandidate(
                        market_id="mkt_1",
                        market_title="Inflation above 4% in 2025",
                        category="macro",
                        market_price=0.44,
                        fair_probability=0.51,
                        edge=0.07,
                        confidence=0.73,
                        liquidity_usd=142000.0,
                        source="inspection",
                    )
                ],
                "scanned_count": 1,
                "skipped_count": 0,
                "warning_messages": [],
            },
        )()

    def list_proposals(self, limit: int = 5):
        return [_build_proposal()]

    def get_proposal_details(self, proposal_id: str):
        if proposal_id != "proposal_91af":
            raise ValueError("Unknown proposal")
        return _build_proposal()

    def list_alerts(self, limit: int = 5):
        return [
            OperatorAlert(
                alert_id="alert_1",
                alert_type=AlertType.PROPOSAL_TTL_NEARING,
                severity=AlertSeverity.WARNING,
                state=AlertState.OPEN,
                entity_type=WatchTargetType.PROPOSAL,
                entity_id="proposal_91af",
                related_market_id="mkt_1",
                related_proposal_id="proposal_91af",
                summary="Proposal proposal_91af is nearing TTL expiry",
                payload={},
                created_at=utc_now(),
            )
        ]

    def poll_notifications(self):
        return self.notifications

    def approve_proposal(self, proposal_id: str, chat_id: int):
        self.approved.append((proposal_id, chat_id))
        proposal = _build_proposal()
        proposal.proposal_id = proposal_id
        proposal.status = ProposalStatus.APPROVED
        return proposal

    def reject_proposal(self, proposal_id: str, chat_id: int):
        self.rejected.append((proposal_id, chat_id))
        proposal = _build_proposal()
        proposal.proposal_id = proposal_id
        proposal.status = ProposalStatus.CANCELLED
        return proposal

    def cancel_proposal(self, proposal_id: str, chat_id: int):
        self.cancelled.append((proposal_id, chat_id))
        proposal = _build_proposal()
        proposal.proposal_id = proposal_id
        proposal.status = ProposalStatus.CANCELLED
        return proposal

    def request_additional_analysis(self, proposal_id: str, chat_id: int):
        self.analysis_requested.append((proposal_id, chat_id))
        latest_snapshot = type(
            "LatestSnapshot",
            (),
            {
                "probability": type("Prob", (), {"fair_probability": 0.61, "confidence": 0.72})(),
            },
        )()
        previous_snapshot = type(
            "PreviousSnapshot",
            (),
            {
                "probability": type("Prob", (), {"fair_probability": 0.56})(),
            },
        )()
        drift = type(
            "Drift",
            (),
            {
                "latest_snapshot": latest_snapshot,
                "previous_snapshot": previous_snapshot,
                "fair_probability_delta": 0.05,
            },
        )()
        review = type(
            "Review",
            (),
            {
                "probability_drift": drift,
                "probability_snapshot": latest_snapshot,
            },
        )()
        return type(
            "Analysis",
            (),
            {
                "proposal": _build_proposal(),
                "decision_review": review,
                "scanner_rationale": "absolute edge exceeds threshold",
            },
        )()


class _FakeTelegramClient:
    def __init__(self, updates=None) -> None:
        self.updates = updates or []
        self.sent_messages: list[tuple[int, str]] = []
        self.sent_messages_with_markup: list[tuple[int, str, dict[str, object] | None]] = []
        self.answered_callbacks: list[tuple[str, str | None]] = []

    def get_updates(self, offset=None, timeout=30):
        return self.updates

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    def send_message_with_markup(self, chat_id: int, text: str, reply_markup: dict[str, object] | None) -> None:
        self.sent_messages.append((chat_id, text))
        self.sent_messages_with_markup.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answered_callbacks.append((callback_query_id, text))

    def close(self) -> None:
        pass


def _build_proposal() -> TradeProposal:
    now = utc_now()
    return TradeProposal(
        proposal_id="proposal_91af",
        market_id="mkt_1",
        market_title="Inflation above 4% in 2025",
        market_category="macro",
        action=TradeAction.BUY,
        side="yes",
        market_price=0.44,
        fair_probability=0.51,
        edge=0.07,
        confidence=0.73,
        model_agreement=2,
        trusted_source_present=True,
        source_types=[SourceType.MAJOR_MEDIA],
        current_size_usd=20.0,
        current_limit_price=0.44,
        recommended_size_usd=20.0,
        max_allowed_size_usd=30.0,
        suggested_limit_price=0.44,
        thesis=["scanner opportunity"],
        risks=["market risk"],
        status=ProposalStatus.PENDING_MANUAL_CONFIRMATION,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(minutes=5),
        policy_decision=PolicyDecision(allowed=True, reasons=[], details={}),
    )


class TelegramOperatorTest(unittest.TestCase):
    def test_authorization_rejects_unauthorized_chat(self) -> None:
        router = TelegramRouter(TelegramOperatorAuth({123}), _FakeTelegramOperatorService())  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 999}, "text": "/status"}})
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].text, "Unauthorized operator.")

    def test_allowlisted_chat_can_run_status(self) -> None:
        router = TelegramRouter(TelegramOperatorAuth({123}), _FakeTelegramOperatorService())  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 123}, "text": "/status"}})
        self.assertEqual(len(replies), 1)
        self.assertIn("Mode: semi_auto", replies[0].text)
        self.assertIn("Live execution: disabled", replies[0].text)

    def test_scan_returns_formatted_opportunities(self) -> None:
        router = TelegramRouter(TelegramOperatorAuth({123}), _FakeTelegramOperatorService())  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 123}, "text": "/scan"}})
        self.assertIn("Scanner results", replies[0].text)
        self.assertIn("Inflation above 4% in 2025", replies[0].text)

    def test_proposals_and_proposal_detail_commands(self) -> None:
        service = _FakeTelegramOperatorService()
        router = TelegramRouter(TelegramOperatorAuth({123}), service)  # type: ignore[arg-type]
        proposals_reply = router.handle_update({"message": {"chat": {"id": 123}, "text": "/proposals"}})[0]
        detail_reply = router.handle_update({"message": {"chat": {"id": 123}, "text": "/proposal proposal_91af"}})[0]
        self.assertIn("Active proposals", proposals_reply.text)
        self.assertIn("proposal_91af", detail_reply.text)
        self.assertIn("Fair probability", detail_reply.text)
        self.assertIsNotNone(detail_reply.reply_markup)

    def test_alerts_command_returns_alerts(self) -> None:
        router = TelegramRouter(TelegramOperatorAuth({123}), _FakeTelegramOperatorService())  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 123}, "text": "/alerts"}})
        self.assertIn("Open alerts", replies[0].text)
        self.assertIn("proposal_ttl_nearing", replies[0].text)

    def test_approve_reject_cancel_and_analysis_commands(self) -> None:
        service = _FakeTelegramOperatorService()
        router = TelegramRouter(TelegramOperatorAuth({123}), service)  # type: ignore[arg-type]
        approve = router.handle_update({"message": {"chat": {"id": 123}, "text": "/approve proposal_91af"}})[0]
        reject = router.handle_update({"message": {"chat": {"id": 123}, "text": "/reject proposal_91af"}})[0]
        cancel = router.handle_update({"message": {"chat": {"id": 123}, "text": "/cancel proposal_91af"}})[0]
        analysis = router.handle_update({"message": {"chat": {"id": 123}, "text": "/analysis proposal_91af"}})[0]
        self.assertIn("Proposal approved", approve.text)
        self.assertIn("Proposal rejected", reject.text)
        self.assertIn("Proposal cancelled", cancel.text)
        self.assertIn("Additional Analysis", analysis.text)
        self.assertEqual(service.approved, [("proposal_91af", 123)])
        self.assertEqual(service.rejected, [("proposal_91af", 123)])
        self.assertEqual(service.cancelled, [("proposal_91af", 123)])
        self.assertEqual(service.analysis_requested, [("proposal_91af", 123)])

    def test_callback_actions_and_unauthorized_rejection(self) -> None:
        service = _FakeTelegramOperatorService()
        router = TelegramRouter(TelegramOperatorAuth({123}), service)  # type: ignore[arg-type]
        replies = router.handle_update(
            {
                "callback_query": {
                    "id": "cb_1",
                    "data": "proposal:approve:proposal_91af",
                    "message": {"chat": {"id": 123}},
                }
            }
        )
        self.assertIn("Proposal approved", replies[0].text)
        self.assertEqual(replies[0].callback_query_id, "cb_1")
        unauthorized = router.handle_update(
            {
                "callback_query": {
                    "id": "cb_2",
                    "data": "proposal:details:proposal_91af",
                    "message": {"chat": {"id": 999}},
                }
            }
        )
        self.assertEqual(unauthorized[0].text, "Unauthorized operator.")

    def test_router_hides_raw_tracebacks(self) -> None:
        service = _FakeTelegramOperatorService()
        service.fail_scan = True
        router = TelegramRouter(TelegramOperatorAuth({123}), service)  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 123}, "text": "/scan"}})
        self.assertIn("Command failed: scanner unavailable", replies[0].text)
        self.assertNotIn("Traceback", replies[0].text)

    def test_notification_formatting_and_dispatch_cycle(self) -> None:
        service = _FakeTelegramOperatorService()
        proposal = _build_proposal()
        service.notifications = [
            TelegramNotification("draft_proposal", proposal),
            TelegramNotification(
                "alert",
                OperatorAlert(
                    alert_id="alert_1",
                    alert_type=AlertType.PROPOSAL_TTL_NEARING,
                    severity=AlertSeverity.WARNING,
                    state=AlertState.OPEN,
                    entity_type=WatchTargetType.PROPOSAL,
                    entity_id="proposal_91af",
                    related_market_id="mkt_1",
                    related_proposal_id="proposal_91af",
                    summary="Proposal proposal_91af is nearing TTL expiry",
                    payload={},
                    created_at=utc_now(),
                ),
            ),
        ]
        client = _FakeTelegramClient(
            updates=[{"update_id": 1, "message": {"chat": {"id": 123}, "text": "/help"}}]
        )
        app = TelegramBotApp(
            client=client,  # type: ignore[arg-type]
            router=TelegramRouter(TelegramOperatorAuth({123}), service),  # type: ignore[arg-type]
            operator_service=service,  # type: ignore[arg-type]
        )
        next_offset = app.run_cycle()
        self.assertEqual(next_offset, 2)
        texts = [text for _, text in client.sent_messages]
        self.assertTrue(any("Telegram operator inbox" in text for text in texts))
        self.assertTrue(any("New Draft Proposal" in text for text in texts))
        self.assertTrue(any("Alert" in text for text in texts))
        self.assertTrue(any(markup is not None for _, _, markup in client.sent_messages_with_markup))

    def test_formatter_diagnostics_message_is_concise(self) -> None:
        text = formatter.notification_message(
            TelegramNotification(
                "diagnostics_failure",
                PolymarketDiagnosticsResult(
                    gamma=DiagnosticCheckResult(False, "gamma down"),
                    clob_rest=DiagnosticCheckResult(True, "reachable"),
                    websocket=DiagnosticCheckResult(True, "reachable"),
                    database=DiagnosticCheckResult(True, "sqlite ready"),
                    overall_ok=False,
                ),
            )
        )
        self.assertIn("Diagnostics failure", text)
        self.assertIn("Gamma: FAIL (gamma down)", text)

    def test_formatter_proposal_action_messages(self) -> None:
        proposal = _build_proposal()
        self.assertIn("Proposal approved", formatter.proposal_action_message("approve", proposal))
        self.assertIn("Additional Analysis", formatter.proposal_analysis_message(_FakeTelegramOperatorService().request_additional_analysis(proposal.proposal_id, 123)))

    def test_cli_telegram_serve_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "bot.db"
            os.environ["BOT_DATABASE_URL"] = f"sqlite:///{db_path}"
            config_dir = Path("config").resolve()
            fake_app = type("FakeApp", (), {"client": _FakeTelegramClient(), "serve_forever": lambda self: None})()
            with patch.dict(
                os.environ,
                {
                    "BOT_DATABASE_URL": f"sqlite:///{db_path}",
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_ALLOWED_CHAT_IDS": "123",
                },
                clear=False,
            ), patch("bot.cli.app.build_telegram_bot_app", return_value=fake_app):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(["--config-dir", str(config_dir), "telegram", "serve"])
                self.assertEqual(exit_code, 0)


class TelegramOperatorIntegrationTest(unittest.TestCase):
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
                data_age_seconds=3,
            )

    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Database(Path(self.temp_dir.name) / "bot.db")
        self.database.initialize()
        self.connection = self.database.connect()
        self.addCleanup(self.connection.close)
        self.proposal_repository = ProposalRepository(self.connection)
        self.audit_repository = AuditRepository(self.connection)
        self.market = Market(
            market_id="mkt_123",
            title="Inflation above 4% by Dec 2026",
            category="crypto",
            liquidity_usd=142000.0,
            spread_pct=0.01,
            resolution_time=utc_now() + timedelta(days=10),
            rules_text="Clear",
            rules_confidence=0.95,
            has_orderbook=True,
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_123",
            fair_probability=0.61,
            confidence=0.72,
            model_agreement=2,
            trusted_source_present=True,
            source_types=[SourceType.MAJOR_MEDIA],
        )
        self.execution_adapter = _FakeExecutionAdapter()
        self.proposal_service = ProposalLifecycleService(
            self.proposal_repository,
            AuditLogService(self.audit_repository),
            ProposalEngine(),
            snapshot_provider=self._FakeSnapshotProvider(self.market, self.probability, current_price=0.49),
            probability_snapshot_repository=ProbabilitySnapshotRepository(self.connection),
        )
        self.execution_service = ExecutionPipelineService(
            self.settings,
            self.execution_adapter,
            OrderIntentRepository(self.connection),
            AuditLogService(self.audit_repository),
            notifications_service=None,
        )
        self.decision_review_service = DecisionReviewService(
            self.proposal_service,
            self.execution_service,
            DecisionReviewRepository(self.connection),
        )
        self.operator_service = TelegramOperatorService(
            settings=self.settings,
            profile="balanced",
            execution_adapter=self.execution_adapter,
            proposal_service=self.proposal_service,
            decision_review_service=self.decision_review_service,
            notifications_service=type("Notifications", (), {"list_alerts": lambda *args, **kwargs: []})(),
            scanner_service=type("Scanner", (), {"scan": lambda *args, **kwargs: None})(),
            diagnostics_service=type("Diagnostics", (), {"run": lambda *args, **kwargs: None})(),
        )

    def _create_proposal(self) -> TradeProposal:
        context = self.proposal_service.proposal_engine.create_default_context(self.market, self.probability, current_price=0.49)
        return self.proposal_service.create(self.settings, context)

    def test_approve_records_telegram_audit_metadata_and_does_not_trigger_execution(self) -> None:
        proposal = self._create_proposal()
        approved = self.operator_service.approve_proposal(proposal.proposal_id, chat_id=777)
        self.assertEqual(approved.status, ProposalStatus.APPROVED)
        self.assertEqual(self.execution_adapter.submit_calls, 0)
        reviews = self.proposal_service.list_review_history(proposal.proposal_id)
        self.assertEqual(reviews[0]["action"], "approve")
        self.assertIn('"source": "telegram"', reviews[0]["payload_json"])
        self.assertIn('"chat_id": 777', reviews[0]["payload_json"])
        audits = self.proposal_service.list_audit_history(proposal.proposal_id)
        self.assertEqual(audits[0]["event_type"], "proposal_approved_manually")
        self.assertIn('"source": "telegram"', audits[0]["payload_json"])
        self.assertIn('"chat_id": 777', audits[0]["payload_json"])

    def test_invalid_transition_returns_readable_message(self) -> None:
        proposal = self._create_proposal()
        self.operator_service.reject_proposal(proposal.proposal_id, chat_id=777)
        router = TelegramRouter(TelegramOperatorAuth({777}), self.operator_service)
        replies = router.handle_update({"message": {"chat": {"id": 777}, "text": f"/approve {proposal.proposal_id}"}})
        self.assertIn("Command failed:", replies[0].text)
        self.assertIn("can no longer be approved", replies[0].text.lower())
        self.assertNotIn("Traceback", replies[0].text)

    def test_request_analysis_records_review_metadata(self) -> None:
        proposal = self._create_proposal()
        self.proposal_service.approve(
            self.settings,
            proposal.proposal_id,
            actor="system",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
        )
        analysis = self.operator_service.request_additional_analysis(proposal.proposal_id, chat_id=555)
        self.assertEqual(analysis.scanner_rationale, "edge detected")
        reviews = self.proposal_service.list_review_history(proposal.proposal_id)
        self.assertEqual(reviews[0]["action"], "request_analysis")
        self.assertIn('"action": "analysis"', reviews[0]["payload_json"])


if __name__ == "__main__":
    unittest.main()
