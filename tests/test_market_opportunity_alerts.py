from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot.adapters.polymarket.models import GammaMarketSummary
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import AlertType
from bot.services.market_research import MarketProposalContext, MarketResearchContext
from bot.services.market_opportunity_alerts import MarketOpportunityAlertService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.storage.db import Database
from bot.storage.repositories import AlertRepository, OrderIntentRepository, ProposalRepository, WatchlistRepository
from bot.utils.time import utc_now


class _FakeMarketCatalogService:
    def __init__(self, markets: list[GammaMarketSummary]) -> None:
        self.markets = markets

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False) -> list[GammaMarketSummary]:
        return self.markets[:limit]


class _FakeMarketResearchService:
    def __init__(self, contexts: dict[str, tuple[MarketProposalContext, MarketResearchContext]]) -> None:
        self.contexts = contexts

    def get_market_proposal_context(self, market_id: str) -> MarketProposalContext:
        return self.contexts.get(
            market_id,
            (
                MarketProposalContext(
                    market_id=market_id,
                    proposals=[],
                    latest_proposal=None,
                    latest_decision_review=None,
                ),
                MarketResearchContext(
                    market_id=market_id,
                    related_proposals=[],
                    latest_probability_snapshot=None,
                    probability_drift=None,
                    latest_decision_review=None,
                    latest_execution_evaluation=None,
                    latest_outcome_analysis=None,
                    latest_learning_analysis=None,
                ),
            ),
        )[0]

    def get_market_research_context(self, market_id: str) -> MarketResearchContext:
        return self.contexts.get(
            market_id,
            (
                MarketProposalContext(
                    market_id=market_id,
                    proposals=[],
                    latest_proposal=None,
                    latest_decision_review=None,
                ),
                MarketResearchContext(
                    market_id=market_id,
                    related_proposals=[],
                    latest_probability_snapshot=None,
                    probability_drift=None,
                    latest_decision_review=None,
                    latest_execution_evaluation=None,
                    latest_outcome_analysis=None,
                    latest_learning_analysis=None,
                ),
            ),
        )[1]


def _context_with_artifacts(market_id: str) -> tuple[MarketProposalContext, MarketResearchContext]:
    proposal = SimpleNamespace(proposal_id="proposal_1", updated_at=utc_now())
    review = SimpleNamespace(created_at=utc_now())
    evaluation = SimpleNamespace(created_at=utc_now())
    proposal_context = MarketProposalContext(
        market_id=market_id,
        proposals=[proposal],
        latest_proposal=proposal,
        latest_decision_review=review,  # type: ignore[arg-type]
    )
    research_context = MarketResearchContext(
        market_id=market_id,
        related_proposals=[proposal],
        latest_probability_snapshot=SimpleNamespace(created_at=utc_now()),  # type: ignore[arg-type]
        probability_drift=None,
        latest_decision_review=review,  # type: ignore[arg-type]
        latest_execution_evaluation=evaluation,  # type: ignore[arg-type]
        latest_outcome_analysis=None,
        latest_learning_analysis=None,
    )
    return proposal_context, research_context


def _market(
    market_id: str,
    *,
    question: str,
    category: str = "politics",
    liquidity_usd: float | None = 10000.0,
    end_days: int | None = None,
    event_title: str | None = None,
    slug: str | None = None,
) -> GammaMarketSummary:
    now = utc_now()
    return GammaMarketSummary(
        market_id=market_id,
        question=question,
        event_id="event_1",
        event_title=event_title,
        slug=slug,
        category=category,
        active=True,
        closed=False,
        archived=False,
        enable_order_book=True,
        liquidity_usd=liquidity_usd,
        volume_usd=12000.0,
        end_time=None if end_days is None else now + timedelta(days=end_days),
        created_at=now,
    )


class MarketOpportunityAlertServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config"))

    def _build_notifications(self, tmp_dir: str) -> OperatorNotificationsService:
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        self.addCleanup(connection.close)
        return OperatorNotificationsService(
            WatchlistRepository(connection),
            AlertRepository(connection),
            ProposalRepository(connection),
            OrderIntentRepository(connection),
        )

    def test_relevance_matching_by_category_and_keyword_creates_new_market_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [
                        _market("m1", question="Senate control 2026?", category="politics"),
                        _market("m2", question="Will tensions rise in Iran?", category="world"),
                    ]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({}),
            )

            result = service.scan(self.settings)

            self.assertEqual(result.relevant_count, 2)
            created_types = {alert.alert_type for alert in result.created_alerts}
            self.assertIn(AlertType.NEW_RELEVANT_MARKET, created_types)
            summaries = [alert.summary for alert in result.created_alerts]
            self.assertTrue(any("Senate control" in summary for summary in summaries))
            self.assertTrue(any("Iran" in summary for summary in summaries))

    def test_country_keyword_sports_markets_do_not_trigger_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [
                        _market(
                            "m1",
                            question="Will Ukraine qualify for the 2026 FIFA World Cup?",
                            category="sports",
                            event_title="2026 FIFA World Cup qualifying",
                            slug="ukraine-world-cup-qualify",
                        ),
                        _market(
                            "m2",
                            question="Will Iran win the 2026 FIFA World Cup?",
                            category="sports",
                            event_title="2026 FIFA World Cup",
                            slug="iran-world-cup-win",
                        ),
                    ]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({}),
            )

            result = service.scan(self.settings)

            self.assertEqual(result.relevant_count, 0)
            self.assertEqual(result.created_alerts, [])

    def test_country_keyword_geopolitical_markets_still_trigger_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [
                        _market(
                            "m1",
                            question="Russia-Ukraine Ceasefire before GTA VI?",
                            category="world",
                            event_title="Russia-Ukraine conflict",
                            slug="russia-ukraine-ceasefire-before-gta-vi",
                        ),
                        _market(
                            "m2",
                            question="Putin out as President of Russia by end of 2026?",
                            category="politics",
                            event_title="Russian politics",
                            slug="putin-out-as-president-of-russia-by-end-of-2026",
                        ),
                    ]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({}),
            )

            result = service.scan(self.settings)

            self.assertEqual(result.relevant_count, 2)
            self.assertTrue(
                any(alert.alert_type == AlertType.NEW_RELEVANT_MARKET for alert in result.created_alerts)
            )

    def test_high_liquidity_resolving_soon_and_potential_context_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [_market("m1", question="BTC above 100k?", category="crypto", liquidity_usd=90000.0, end_days=2)]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({"m1": _context_with_artifacts("m1")}),
            )

            result = service.scan(self.settings)

            created_types = {alert.alert_type for alert in result.created_alerts}
            self.assertIn(AlertType.NEW_RELEVANT_MARKET, created_types)
            self.assertIn(AlertType.HIGH_LIQUIDITY_MARKET, created_types)
            self.assertIn(AlertType.RESOLVING_SOON_MARKET, created_types)
            self.assertIn(AlertType.POTENTIAL_CONTEXT_MARKET, created_types)

    def test_dedupe_prevents_duplicate_open_or_repeated_market_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [_market("m1", question="BTC above 100k?", category="crypto", liquidity_usd=90000.0)]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({}),
            )

            first = service.scan(self.settings)
            second = service.scan(self.settings)

            self.assertGreaterEqual(len(first.created_alerts), 1)
            self.assertEqual(second.created_alerts, [])

    def test_potential_context_alert_is_omitted_without_explicit_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notifications = self._build_notifications(tmp_dir)
            settings = replace(
                self.settings,
                market_opportunity_alerts=replace(
                    self.settings.market_opportunity_alerts,
                    enabled_alert_types=["potential_context_market"],
                ),
            )
            service = MarketOpportunityAlertService(
                market_catalog_service=_FakeMarketCatalogService(
                    [_market("m1", question="Will Russia sanctions expand?", category="world")]
                ),
                notifications_service=notifications,
                market_research_service=_FakeMarketResearchService({}),
            )

            result = service.scan(settings)

            self.assertEqual(result.created_alerts, [])

    def test_cli_scan_opportunities_is_operator_readable(self) -> None:
        fake_result = SimpleNamespace(
            created_alerts=[
                SimpleNamespace(
                    created_at=utc_now(),
                    alert_id="alert_1",
                    severity=SimpleNamespace(value="warning"),
                    state=SimpleNamespace(value="open"),
                    alert_type=SimpleNamespace(value="high_liquidity_market"),
                    entity_type=SimpleNamespace(value="market"),
                    entity_id="m1",
                    summary="High-liquidity relevant market: BTC above 100k?",
                )
            ],
            scanned_count=50,
            relevant_count=3,
            warning_messages=[],
        )
        fake_container = SimpleNamespace(
            market_data_service=None,
            realtime_market_feed_service=None,
            market_catalog_service=None,
            market_opportunity_alert_service=SimpleNamespace(scan=lambda settings, limit=200: fake_result),
            market_opportunity_scanner=None,
            proposal_service=None,
            opportunity_bridge_service=None,
            notifications_service=None,
            execution_service=None,
            analytics_service=None,
            decision_review_service=None,
            execution_evaluation_service=None,
            outcome_analysis_service=None,
            saved_view_service=None,
            reporting_service=None,
            position_repository=None,
            telegram_operator_service=None,
            dashboard_app=lambda: None,
            close=lambda: None,
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer), patch("bot.cli.app.build_app_container", return_value=fake_container):
            exit_code = main(["--config-dir", "config", "alerts", "scan-opportunities", "--limit", "25"])
        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Market opportunity alert scan", output)
        self.assertIn("created_alert_count: 1", output)
        self.assertIn("high_liquidity_market", output)


if __name__ == "__main__":
    unittest.main()
