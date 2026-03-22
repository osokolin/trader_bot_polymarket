from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import ExecutionPreviewStatus, SourceType
from bot.domain.models import Market, ProbabilityEstimate
from bot.integrations.polymarket_gateway import PolymarketGatewayMetadata, PolymarketGatewayQuote
from bot.services.audit_log import AuditLogService
from bot.services.execution_preview import ExecutionPreviewService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.db import Database
from bot.storage.repositories import AuditRepository, ExecutionPreviewRepository, OrderIntentRepository, ProposalRepository
from bot.adapters.polymarket.trading import SemiAutoExecutionAdapter
from bot.utils.time import utc_now


class _FakeGateway:
    def __init__(self, *, enabled: bool = True, metadata: PolymarketGatewayMetadata | None = None, quote: PolymarketGatewayQuote | None = None) -> None:
        self.config = SimpleNamespace(enable_polymarket_gateway=enabled)
        self._metadata = metadata
        self._quote = quote

    def get_market_metadata(self, market_id: str) -> PolymarketGatewayMetadata:
        if self._metadata is None:
            raise RuntimeError("metadata unavailable")
        return self._metadata

    def quote_order(self, order) -> PolymarketGatewayQuote:
        if self._quote is None:
            raise RuntimeError("quote unavailable")
        return self._quote


class _FakeExecutionPreviewService:
    def __init__(self, preview, previews: list | None = None, summary=None) -> None:
        self.preview = preview
        self.previews = [] if previews is None else previews
        self.summary = summary or SimpleNamespace(
            total_count=len(self.previews),
            success_count=0,
            warning_count=0,
            failure_count=0,
            top_validation_errors=[],
            top_warnings=[],
        )
        self.called_with: list[str] = []
        self.history_called_with: list[tuple[str, int]] = []
        self.list_called_with: list[tuple[str, int]] = []
        self.summary_called = 0

    def preview_proposal(self, proposal_id: str):
        self.called_with.append(proposal_id)
        return self.preview

    def list_preview_history_for_proposal(self, proposal_id: str, limit: int = 20):
        self.history_called_with.append((proposal_id, limit))
        return self.previews

    def list_recent_previews(self, limit: int = 20):
        self.list_called_with.append(("recent", limit))
        return self.previews

    def list_failed_previews(self, limit: int = 20):
        self.list_called_with.append(("failed", limit))
        return self.previews

    def list_warning_previews(self, limit: int = 20):
        self.list_called_with.append(("warnings", limit))
        return self.previews

    def summarize_previews(self):
        self.summary_called += 1
        return self.summary


class ExecutionPreviewServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "bot.db"
        self.database = Database(self.db_path)
        self.database.initialize()
        self.connection = self.database.connect()
        self.audit_log = AuditLogService(AuditRepository(self.connection))
        self.preview_repository = ExecutionPreviewRepository(self.connection)
        self.proposal_service = ProposalLifecycleService(
            ProposalRepository(self.connection),
            self.audit_log,
            ProposalEngine(),
        )
        now = utc_now()
        self.market = Market(
            market_id="mkt_preview",
            title="Will BTC close above 100k?",
            category="crypto",
            liquidity_usd=15000,
            spread_pct=0.02,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear market rules",
            rules_confidence=0.98,
            tags=["crypto"],
            has_orderbook=True,
            event_id="evt_preview",
        )
        self.probability = ProbabilityEstimate(
            market_id="mkt_preview",
            fair_probability=0.62,
            confidence=0.84,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
        )
        self.pending = self.proposal_service.create(
            self.settings,
            self.proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.55),
        )
        self.approved = self.proposal_service.approve(
            self.settings,
            self.pending.proposal_id,
            actor="preview-test",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.market,
            probability=self.probability,
            data_age_seconds=0,
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def _metadata(self, *, market_id: str = "mkt_preview", token_map: dict[str, str] | None = None, asset_id: str = "asset_yes") -> PolymarketGatewayMetadata:
        token_map = {} if token_map is None else token_map
        return PolymarketGatewayMetadata(
            market=self.market if market_id == self.market.market_id else Market(
                market_id=market_id,
                title=self.market.title,
                category=self.market.category,
                liquidity_usd=self.market.liquidity_usd,
                spread_pct=self.market.spread_pct,
                resolution_time=self.market.resolution_time,
                rules_text=self.market.rules_text,
                rules_confidence=self.market.rules_confidence,
                tags=self.market.tags,
                has_orderbook=self.market.has_orderbook,
                event_id=self.market.event_id,
            ),
            asset_id=asset_id,
            slug="btc-above-100k",
            event_title="BTC price milestones",
            event_id="evt_preview",
            condition_id="cond_123",
            outcome_token_ids=token_map,
            gamma_payload={"id": market_id},
        )

    def _quote(self, *, quoted_price: float = 0.55) -> PolymarketGatewayQuote:
        return PolymarketGatewayQuote(
            market_id="mkt_preview",
            side="yes",
            size_usd=self.approved.current_size_usd,
            limit_price=self.approved.current_limit_price,
            reference_price=quoted_price,
            estimated_shares=round(self.approved.current_size_usd / self.approved.current_limit_price, 4),
            dry_run=True,
            message="Prepared gateway quote",
        )

    def test_preview_path_is_blocked_by_default_when_gateway_is_missing(self) -> None:
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=None,
        )
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.BLOCKED)
        self.assertTrue(preview.dry_run)
        self.assertIn("polymarket gateway is not configured", preview.validation_errors)
        persisted = self.preview_repository.list_for_proposal(self.approved.proposal_id)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].status, ExecutionPreviewStatus.BLOCKED)

    def test_preview_generation_success(self) -> None:
        gateway = _FakeGateway(
            metadata=self._metadata(token_map={"yes": "tok_yes", "no": "tok_no"}),
            quote=self._quote(),
        )
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=gateway,
        )  # type: ignore[arg-type]
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.READY)
        self.assertTrue(preview.dry_run)
        self.assertEqual(preview.source, "polymarket_gateway")
        self.assertEqual(preview.market_id, self.approved.market_id)
        self.assertEqual(preview.token_id, "tok_yes")
        self.assertEqual(preview.quoted_price, 0.55)
        self.assertNotIn("private_key", str(preview.preview_payload))
        persisted = self.preview_repository.list_for_proposal(self.approved.proposal_id)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].status, ExecutionPreviewStatus.READY)
        self.assertTrue(persisted[0].dry_run)

    def test_preview_is_blocked_when_gateway_is_disabled(self) -> None:
        gateway = _FakeGateway(
            enabled=False,
            metadata=self._metadata(token_map={"yes": "tok_yes"}),
            quote=self._quote(),
        )
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=gateway,
        )  # type: ignore[arg-type]
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.BLOCKED)
        self.assertIn("polymarket gateway is disabled", preview.validation_errors)

    def test_preview_generation_reports_market_resolution_mismatch(self) -> None:
        gateway = _FakeGateway(
            metadata=self._metadata(market_id="mkt_other", token_map={}, asset_id=""),
            quote=self._quote(),
        )
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=gateway,
        )  # type: ignore[arg-type]
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.BLOCKED)
        self.assertIn("gateway market resolution does not match proposal market_id", preview.validation_errors)

    def test_preview_is_non_live_even_with_warnings(self) -> None:
        gateway = _FakeGateway(
            metadata=self._metadata(token_map={}, asset_id="asset_fallback"),
            quote=self._quote(quoted_price=0.58),
        )
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=gateway,
        )  # type: ignore[arg-type]
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.READY_WITH_WARNINGS)
        self.assertTrue(preview.dry_run)
        self.assertIn("side-specific token for yes was not resolved", " ".join(preview.warnings))
        self.assertIn("quoted price differs materially", " ".join(preview.warnings))
        persisted = self.preview_repository.list_with_warnings()
        self.assertEqual(len(persisted), 1)
        self.assertNotIn("private_key", str(persisted[0].preview_payload))

    def test_preview_is_blocked_when_token_resolution_fails(self) -> None:
        gateway = _FakeGateway(
            metadata=self._metadata(token_map={}, asset_id=""),
            quote=self._quote(),
        )
        service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=gateway,
        )  # type: ignore[arg-type]
        preview = service.preview_proposal(self.approved.proposal_id)
        self.assertEqual(preview.status, ExecutionPreviewStatus.BLOCKED)
        self.assertIn("gateway metadata did not expose a token id", preview.validation_errors)

    def test_preview_history_and_summary_are_available(self) -> None:
        ready_gateway = _FakeGateway(
            metadata=self._metadata(token_map={"yes": "tok_yes", "no": "tok_no"}),
            quote=self._quote(),
        )
        warning_gateway = _FakeGateway(
            metadata=self._metadata(token_map={}, asset_id="asset_fallback"),
            quote=self._quote(quoted_price=0.58),
        )
        failed_gateway = _FakeGateway(
            metadata=self._metadata(token_map={}, asset_id=""),
            quote=self._quote(),
        )
        ready_service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=ready_gateway,
        )  # type: ignore[arg-type]
        warning_service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=warning_gateway,
        )  # type: ignore[arg-type]
        failed_service = ExecutionPreviewService(
            self.proposal_service,
            self.audit_log,
            self.preview_repository,
            polymarket_gateway=failed_gateway,
        )  # type: ignore[arg-type]
        ready_service.preview_proposal(self.approved.proposal_id)
        warning_service.preview_proposal(self.approved.proposal_id)
        failed_service.preview_proposal(self.approved.proposal_id)

        proposal_history = ready_service.list_preview_history_for_proposal(self.approved.proposal_id, limit=10)
        self.assertEqual(len(proposal_history), 3)
        self.assertEqual(len(ready_service.list_failed_previews(limit=10)), 1)
        self.assertEqual(len(ready_service.list_warning_previews(limit=10)), 1)
        summary = ready_service.summarize_previews()
        self.assertEqual(summary.total_count, 3)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.warning_count, 1)
        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(summary.top_validation_errors[0][0], "gateway metadata did not expose a token id")
        self.assertEqual(summary.top_warnings[0][0], "side-specific token for yes was not resolved; using gateway asset_id fallback")

    def test_existing_execution_path_remains_unchanged(self) -> None:
        execution_service = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            OrderIntentRepository(self.connection),
            self.audit_log,
        )
        intent = execution_service.create_order_intent(self.approved)
        outcome = execution_service.prepare_submission(intent.intent_id)
        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.stage, "prepared")


class ExecutionPreviewCliTest(unittest.TestCase):
    def test_cli_proposal_execution_preview_path_is_explicit(self) -> None:
        settings = load_settings(Path("config"))
        preview = SimpleNamespace(
            preview_id="preview_1",
            proposal_id="proposal_1",
            source="polymarket_gateway",
            dry_run=True,
            status=ExecutionPreviewStatus.READY,
            market_id="mkt_preview",
            event_id="evt_preview",
            condition_id="cond_123",
            token_id="tok_yes",
            side="yes",
            intended_price=0.55,
            quoted_price=0.55,
            intended_size_usd=25.0,
            normalized_size_usd=25.0,
            estimated_shares=45.4545,
            warnings=[],
            validation_errors=[],
            preview_payload={"source": "polymarket_gateway", "dry_run": True},
            created_at=utc_now(),
        )
        fake_service = _FakeExecutionPreviewService(
            preview,
            previews=[preview],
            summary=SimpleNamespace(
                total_count=1,
                success_count=1,
                warning_count=0,
                failure_count=0,
                top_validation_errors=[],
                top_warnings=[],
            ),
        )
        fake_container = SimpleNamespace(
            market_data_service=None,
            realtime_market_feed_service=None,
            market_catalog_service=None,
            market_opportunity_alert_service=None,
            market_opportunity_scanner=None,
            proposal_service=None,
            opportunity_bridge_service=None,
            notifications_service=None,
            execution_service=None,
            execution_preview_service=fake_service,
            analytics_service=None,
            decision_review_service=None,
            execution_evaluation_service=None,
            outcome_analysis_service=None,
            saved_view_service=None,
            reporting_service=None,
            position_repository=None,
            telegram_operator_service=None,
            web_auth_service=None,
            close=lambda: None,
        )
        with patch("bot.cli.app.load_app_settings", return_value=settings), patch(
            "bot.cli.app.build_app_container",
            return_value=fake_container,
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["proposals", "execution-preview", "proposal_1"])
        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("source: polymarket_gateway", output)
        self.assertIn("dry_run: True", output)
        self.assertIn("status: ready", output)
        self.assertEqual(fake_service.called_with, ["proposal_1"])

    def test_cli_execution_preview_history_and_summary_are_operator_readable(self) -> None:
        settings = load_settings(Path("config"))
        preview = SimpleNamespace(
            preview_id="preview_1",
            proposal_id="proposal_1",
            source="polymarket_gateway",
            dry_run=True,
            status=ExecutionPreviewStatus.BLOCKED,
            market_id="mkt_preview",
            event_id="evt_preview",
            condition_id="cond_123",
            token_id=None,
            side="yes",
            intended_price=0.55,
            quoted_price=None,
            intended_size_usd=25.0,
            normalized_size_usd=None,
            estimated_shares=None,
            warnings=[],
            validation_errors=["gateway metadata did not expose a token id"],
            preview_payload={"source": "polymarket_gateway", "dry_run": True},
            created_at=utc_now(),
        )
        fake_service = _FakeExecutionPreviewService(
            preview,
            previews=[preview],
            summary=SimpleNamespace(
                total_count=3,
                success_count=1,
                warning_count=1,
                failure_count=1,
                top_validation_errors=[("gateway metadata did not expose a token id", 1)],
                top_warnings=[("quoted price differs materially from proposal limit price", 1)],
            ),
        )
        fake_container = SimpleNamespace(
            market_data_service=None,
            realtime_market_feed_service=None,
            market_catalog_service=None,
            market_opportunity_alert_service=None,
            market_opportunity_scanner=None,
            proposal_service=None,
            opportunity_bridge_service=None,
            notifications_service=None,
            execution_service=None,
            execution_preview_service=fake_service,
            analytics_service=None,
            decision_review_service=None,
            execution_evaluation_service=None,
            outcome_analysis_service=None,
            saved_view_service=None,
            reporting_service=None,
            position_repository=None,
            telegram_operator_service=None,
            web_auth_service=None,
            close=lambda: None,
        )
        with patch("bot.cli.app.load_app_settings", return_value=settings), patch(
            "bot.cli.app.build_app_container",
            return_value=fake_container,
        ):
            history_buffer = io.StringIO()
            with redirect_stdout(history_buffer):
                history_exit_code = main(["execution-previews", "list", "--scope", "failed", "--limit", "5"])
            summary_buffer = io.StringIO()
            with redirect_stdout(summary_buffer):
                summary_exit_code = main(["execution-previews", "summary"])
        self.assertEqual(history_exit_code, 0)
        self.assertEqual(summary_exit_code, 0)
        self.assertIn("preview_scope: failed", history_buffer.getvalue())
        self.assertIn("blocked", history_buffer.getvalue())
        self.assertIn("total_previews: 3", summary_buffer.getvalue())
        self.assertIn("failure_count: 1", summary_buffer.getvalue())
        self.assertEqual(fake_service.list_called_with, [("failed", 5)])
        self.assertEqual(fake_service.summary_called, 1)


if __name__ == "__main__":
    unittest.main()
