from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.cli.app import main
from bot.domain.decisions import PolicyDecision
from bot.domain.enums import AlertSeverity, AlertState, AlertType, ProposalStatus, SourceType, TradeAction, WatchTargetType
from bot.domain.models import OperatorAlert, OpportunityCandidate, TradeProposal
from bot.services.polymarket_diagnostics import DiagnosticCheckResult, PolymarketDiagnosticsResult
from bot.services.telegram_operator_service import TelegramNotification
from bot.telegram import formatter
from bot.telegram.auth import TelegramOperatorAuth
from bot.telegram.bot_app import TelegramBotApp
from bot.telegram.router import TelegramRouter
from bot.utils.time import utc_now


class _FakeExecutionAdapter:
    supports_live_execution = False


class _FakeTelegramOperatorService:
    def __init__(self) -> None:
        self.fail_scan = False
        self.notifications = []

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


class _FakeTelegramClient:
    def __init__(self, updates=None) -> None:
        self.updates = updates or []
        self.sent_messages: list[tuple[int, str]] = []

    def get_updates(self, offset=None, timeout=30):
        return self.updates

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

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

    def test_alerts_command_returns_alerts(self) -> None:
        router = TelegramRouter(TelegramOperatorAuth({123}), _FakeTelegramOperatorService())  # type: ignore[arg-type]
        replies = router.handle_update({"message": {"chat": {"id": 123}, "text": "/alerts"}})
        self.assertIn("Open alerts", replies[0].text)
        self.assertIn("proposal_ttl_nearing", replies[0].text)

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


if __name__ == "__main__":
    unittest.main()
