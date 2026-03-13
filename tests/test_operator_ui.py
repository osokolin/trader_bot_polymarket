from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.cli.app import main
from bot.config.loader import load_settings
from bot.domain.enums import SourceType, WatchTargetType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.analytics import AnalyticsService
from bot.services.audit_log import AuditLogService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.market_catalog import MarketCatalogBrowseQuery, MarketCatalogBrowseResult
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_engine import ProposalEngine
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.reporting import ReportingService
from bot.services.saved_views import SavedViewService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    OrderIntentRepository,
    OutcomeAnalysisRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
    SavedViewRepository,
    WatchlistRepository,
)
from bot.ui import OperatorDashboardApp, OperatorDashboardServices
from bot.utils.time import utc_now


class OperatorUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config_dir = Path("config").resolve()
        self.settings = load_settings(self.config_dir)
        now = utc_now()
        self.market = Market(
            market_id="mkt_ui_primary",
            title="Will CPI print below consensus?",
            category="crypto",
            liquidity_usd=25000,
            spread_pct=0.01,
            resolution_time=now.replace(year=now.year + 1),
            rules_text="Clear rules",
            rules_confidence=0.98,
            tags=["macro"],
            has_orderbook=True,
        )
        self.other_market = replace(
            self.market,
            market_id="mkt_ui_other",
            title="Will payrolls beat estimates?",
            category="politics",
        )
        self.probability = ProbabilityEstimate(
            market_id=self.market.market_id,
            fair_probability=0.72,
            confidence=0.9,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
            key_factors=["policy drift", "labor slowdown"],
            source_count=2,
            confidence_components={"model": 0.88, "liquidity": 1.0},
        )

    def test_dashboard_routes_render_operator_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection, app, approved_id, pending_id, intent_id, alert_id = self._build_fixture(tmp_dir)
            try:
                status, home = app.render_response("/")
                self.assertEqual(status, "200 OK")
                self.assertIn("Панель оператора", home)
                self.assertIn(approved_id, home)
                self.assertIn(intent_id, home)
                self.assertIn("открытые алерты", home)
                self.assertIn("Последние разборы решений", home)
                self.assertIn("Последний анализ итогов", home)
                self.assertIn("Последние оценки исполнения", home)
                self.assertIn("Последняя симуляция", home)
                self.assertIn("Недавние алерты", home)

                _, proposals = app.render_response("/proposals", f"scope=approved&market_id={self.market.market_id}")
                self.assertIn(approved_id, proposals)
                self.assertNotIn(pending_id, proposals)
                self.assertIn("/proposals/latest-approved", proposals)

                _, proposal_detail = app.render_response(f"/proposals/{approved_id}")
                self.assertIn(f"/research/proposals/{approved_id}", proposal_detail)
                self.assertIn(f"/decision-reviews/proposals/{approved_id}", proposal_detail)
                self.assertIn("Тонкая карточка", proposal_detail)

                _, intents = app.render_response("/intents", f"scope=terminal&proposal_id={approved_id}")
                self.assertIn(intent_id, intents)
                self.assertIn("/intents/latest-terminal", intents)

                _, alerts = app.render_response("/alerts", "state=open&watchlist_only=1")
                self.assertIn("предложение близко к TTL", alerts)
                self.assertIn("Возвращено", alerts)
                self.assertIn(f"/alerts/{alert_id}/acknowledge", alerts)

                _, alert_updated = app.render_response(f"/alerts/{alert_id}/acknowledge", "return_to=/alerts?state=open")
                self.assertIn("Алерт обновлен", alert_updated)
                self.assertIn("подтвержден", alert_updated)
                self.assertIn("переведен в состояние", alert_updated)
                self.assertIn("/alerts?state=open", alert_updated)

                _, research = app.render_response(f"/research/proposals/{approved_id}")
                self.assertIn("Снимок предложения", research)
                self.assertIn("Сводка дрейфа", research)
                self.assertIn("policy drift", research)
            finally:
                connection.close()

    def test_dashboard_decision_review_analysis_and_cli_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            connection, app, approved_id, _, intent_id, _ = self._build_fixture(tmp_dir)
            try:
                _, review = app.render_response(f"/decision-reviews/proposals/{approved_id}")
                self.assertIn("Разбор решения", review)
                self.assertIn("уверенность=", review)
                self.assertIn("вероятность=", review)
                self.assertIn("Оценка исполнения", review)
                self.assertIn("Вердикт", review)

                _, latest_review = app.render_response("/decision-reviews/proposals/latest-approved")
                self.assertIn(approved_id, latest_review)

                _, analysis = app.render_response("/analysis", "scope=outcomes&group_by=market&latest=1")
                self.assertIn("Анализ итогов", analysis)
                self.assertIn(self.market.market_id, analysis)
                self.assertIn("уверенность сохранилась", analysis)

                _, latest_terminal = app.render_response("/intents/latest-terminal")
                self.assertIn(intent_id, latest_terminal)

                _, research_index = app.render_response("/research", f"market_id={self.market.market_id}")
                self.assertIn(f"/research/markets/{self.market.market_id}", research_index)
                self.assertIn(f"/decision-reviews/markets/{self.market.market_id}", research_index)

                _, market_catalog = app.render_response("/catalog/markets")
                self.assertIn("Каталог рынков", market_catalog)
                self.assertIn("Will CPI print below consensus?", market_catalog)
                self.assertIn(f"/markets/live/{self.market.market_id}", market_catalog)
                self.assertIn("Категории", market_catalog)
                self.assertIn("сохранить текущий вид", market_catalog)
                self.assertIn("Macro Signals", market_catalog)

                _, event_catalog = app.render_response("/catalog/events")
                self.assertIn("Каталог событий", event_catalog)
                self.assertIn("Macro Calendar", event_catalog)

                _, market_catalog_filtered = app.render_response(
                    "/catalog/markets",
                    "scope=all&category=politics&search=payrolls&min_liquidity=1000&orderbook_only=true&sort=volume_desc&limit=20",
                )
                self.assertIn("Will payrolls beat estimates?", market_catalog_filtered)
                self.assertNotIn("Will CPI print below consensus?", market_catalog_filtered)

                saved_view_service = app.services.saved_view_service
                saved_view_service.save(
                    "catalog-markets-default",
                    "markets_catalog",
                    {"scope": "all", "categories": ["politics"], "search": "payrolls", "sort": "volume_desc", "limit": 20},
                )
                _, market_catalog_saved = app.render_response("/catalog/markets")
                self.assertIn("Will payrolls beat estimates?", market_catalog_saved)
                self.assertNotIn("Will CPI print below consensus?", market_catalog_saved)
                self.assertIn("/views/catalog-markets-default", market_catalog_saved)

                _, missing_market_review = app.render_response("/decision-reviews/markets/mkt_missing_snapshot")
                self.assertIn("Разбор пока недоступен", missing_market_review)
                self.assertIn("/markets/live/mkt_missing_snapshot", missing_market_review)

                _, views = app.render_response("/views")
                self.assertIn("Сохраненные виды", views)
                self.assertIn("approved-proposals", views)
                self.assertIn("сохранить текущий фильтр предложений", views)

                _, saved_view = app.render_response("/views/approved-proposals")
                self.assertIn("запустить вид", saved_view)
                self.assertIn("клонировать", saved_view)
                self.assertIn("редактировать", saved_view)

                _, saved_view_run = app.render_response("/views/approved-proposals/run")
                self.assertIn("Список предложений", saved_view_run)
                self.assertIn(approved_id, saved_view_run)

                _, cloned_view = app.render_response("/views/approved-proposals/clone", "name=approved-proposals-copy")
                self.assertIn("Сохраненный вид клонирован", cloned_view)
                self.assertIn("approved-proposals-copy", cloned_view)

                _, edited_view = app.render_response("/views/approved-proposals/edit", "scope=all&name=approved-proposals")
                self.assertIn("Сохраненный вид обновлен", edited_view)
                self.assertIn("Параметры", edited_view)

                _, current_saved = app.render_response(
                    "/views/save-current",
                    "name=alert-open-ui&kind=alerts_list&state=open&watchlist_only=true",
                )
                self.assertIn("Текущий фильтр сохранен", current_saved)
                self.assertIn("alert-open-ui", current_saved)

                _, catalog_saved = app.render_response(
                    "/views/save-current",
                    "name=catalog-markets-default&kind=markets_catalog&scope=all&category=crypto&category=politics&search=payrolls&sort=volume_desc&limit=20",
                )
                self.assertIn("catalog-markets-default", catalog_saved)
                saved_catalog = app.services.saved_view_service.get("catalog-markets-default")
                self.assertEqual(saved_catalog.params["categories"], ["crypto", "politics"])
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_cwd = Path.cwd()
            os.chdir(tmp_dir)
            try:
                with patch("bot.cli.app.serve_ui") as mocked_serve_ui:
                    exit_code = main(
                        [
                            "--config-dir",
                            str(self.config_dir),
                            "ui",
                            "serve",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            "8099",
                        ]
                    )
                self.assertEqual(exit_code, 0)
                mocked_serve_ui.assert_called_once()
                app_arg, host_arg, port_arg = mocked_serve_ui.call_args.args
                self.assertIsInstance(app_arg, OperatorDashboardApp)
                self.assertEqual(host_arg, "127.0.0.1")
                self.assertEqual(port_arg, 8099)
            finally:
                os.chdir(original_cwd)

    def _build_fixture(self, tmp_dir: str):
        database = Database(Path(tmp_dir) / "bot.db")
        database.initialize()
        connection = database.connect()
        proposal_repository = ProposalRepository(connection)
        intent_repository = OrderIntentRepository(connection)
        audit_log = AuditLogService(AuditRepository(connection))
        proposal_service = ProposalLifecycleService(
            proposal_repository,
            audit_log,
            ProposalEngine(),
            probability_snapshot_repository=ProbabilitySnapshotRepository(connection),
        )
        notifications_service = OperatorNotificationsService(
            WatchlistRepository(connection),
            AlertRepository(connection),
            proposal_repository,
            intent_repository,
        )
        execution_service = ExecutionPipelineService(
            self.settings,
            SemiAutoExecutionAdapter(),
            intent_repository,
            audit_log,
            paper_execution_adapter=PaperExecutionAdapter(),
            notifications_service=notifications_service,
        )
        decision_review_service = DecisionReviewService(
            proposal_service,
            execution_service,
            DecisionReviewRepository(connection),
        )
        execution_evaluation_service = ExecutionEvaluationService(
            proposal_service,
            execution_service,
            ExecutionEvaluationRepository(connection),
        )
        outcome_analysis_service = OutcomeAnalysisService(
            proposal_service,
            DecisionReviewRepository(connection),
            ExecutionEvaluationRepository(connection),
            OutcomeAnalysisRepository(connection),
        )
        saved_view_service = SavedViewService(SavedViewRepository(connection))
        reporting_service = ReportingService(
            DecisionReviewRepository(connection),
            execution_evaluation_service,
            outcome_analysis_service,
            notifications_service,
            AnalyticsService(proposal_service, execution_service),
        )
        market_catalog_service = _FakeMarketCatalogService(self.market, self.other_market)

        pending = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(
                self.other_market,
                replace(self.probability, market_id=self.other_market.market_id),
                0.45,
            ),
        )
        proposal_repository.save(replace(pending, expires_at=utc_now() + timedelta(minutes=5), updated_at=utc_now()))

        proposal = proposal_service.create(
            self.settings,
            proposal_service.proposal_engine.create_default_context(self.market, self.probability, 0.45),
        )
        approved = proposal_service.approve(
            self.settings,
            proposal.proposal_id,
            actor="ui-test",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=self.market,
            probability=replace(
                self.probability,
                fair_probability=0.68,
                confidence=0.91,
                market_id=self.market.market_id,
                source_count=3,
                key_factors=["policy drift", "labor slowdown", "rates repricing"],
                confidence_components={"model": 0.9, "liquidity": 1.0, "spread": 0.99},
            ),
            data_age_seconds=0,
        )
        intent = execution_service.create_order_intent(approved)
        execution_service.prepare_submission(intent.intent_id)
        execution_service.simulate_intent(intent.intent_id, actor="ui-test")

        notifications_service.add_watch(WatchTargetType.PROPOSAL, pending.proposal_id, "pending ttl")
        alerts = notifications_service.scan()

        decision_review_service.create_for_proposal(approved.proposal_id)
        decision_review_service.create_for_market(approved.market_id)
        execution_evaluation_service.evaluate_proposal(approved.proposal_id)
        outcome_analysis_service.summarize_outcomes("market")
        outcome_analysis_service.summarize_learning("category")
        saved_view_service.save("approved-proposals", "proposals_list", {"scope": "approved", "limit": 5, "offset": 0, "sort": "updated_desc"})

        app = OperatorDashboardApp(
            OperatorDashboardServices(
                proposal_service=proposal_service,
                execution_service=execution_service,
                notifications_service=notifications_service,
                decision_review_service=decision_review_service,
                execution_evaluation_service=execution_evaluation_service,
                outcome_analysis_service=outcome_analysis_service,
                saved_view_service=saved_view_service,
                reporting_service=reporting_service,
                market_catalog_service=market_catalog_service,
            )
        )
        return connection, app, approved.proposal_id, pending.proposal_id, intent.intent_id, alerts[0].alert_id


class _FakeMarketCatalogService:
    def __init__(self, primary_market: Market, secondary_market: Market) -> None:
        self.primary_market = primary_market
        self.secondary_market = secondary_market
        self.browse_calls: list[MarketCatalogBrowseQuery] = []

    def list_markets(self, limit: int = 20, active: bool = True, closed: bool = False):
        from bot.adapters.polymarket.models import GammaMarketSummary

        return [
            GammaMarketSummary(
                market_id=self.primary_market.market_id,
                question=self.primary_market.title,
                event_id="evt_macro",
                event_title="Macro Signals",
                slug="cpi-below-consensus",
                category=self.primary_market.category,
                active=True,
                closed=False,
                archived=False,
                enable_order_book=True,
                liquidity_usd=self.primary_market.liquidity_usd,
                volume_usd=10000.0,
            ),
            GammaMarketSummary(
                market_id=self.secondary_market.market_id,
                question=self.secondary_market.title,
                event_id="evt_macro",
                event_title="Macro Signals",
                slug="payrolls-beat-estimates",
                category=self.secondary_market.category,
                active=True,
                closed=False,
                archived=False,
                enable_order_book=True,
                liquidity_usd=self.secondary_market.liquidity_usd,
                volume_usd=8000.0,
            ),
        ][:limit]

    def list_events(self, limit: int = 20, active: bool = True, closed: bool = False):
        from bot.adapters.polymarket.models import GammaEventSummary

        return [
            GammaEventSummary(
                event_id="evt_macro",
                title="Macro Calendar",
                slug="macro-calendar",
                active=True,
                closed=False,
                archived=False,
                market_count=2,
            )
        ][:limit]

    def browse_markets(self, query: MarketCatalogBrowseQuery) -> MarketCatalogBrowseResult:
        from bot.adapters.polymarket.models import GammaMarketSummary

        self.browse_calls.append(query)
        items = [
            GammaMarketSummary(
                market_id=self.primary_market.market_id,
                question=self.primary_market.title,
                event_id="evt_macro",
                event_title="Macro Signals",
                slug="cpi-below-consensus",
                category=self.primary_market.category,
                active=True,
                closed=False,
                archived=False,
                enable_order_book=True,
                liquidity_usd=self.primary_market.liquidity_usd,
                volume_usd=10000.0,
            ),
            GammaMarketSummary(
                market_id=self.secondary_market.market_id,
                question=self.secondary_market.title,
                event_id="evt_macro",
                event_title="Macro Signals",
                slug="payrolls-beat-estimates",
                category=self.secondary_market.category,
                active=True,
                closed=False,
                archived=False,
                enable_order_book=True,
                liquidity_usd=self.secondary_market.liquidity_usd,
                volume_usd=8000.0,
            ),
        ]
        filtered = []
        normalized_categories = {value.lower() for value in query.categories}
        for item in items:
            if normalized_categories and item.category.lower() not in normalized_categories:
                continue
            if query.search and query.search.lower() not in item.question.lower() and query.search.lower() not in (item.slug or "").lower():
                continue
            if query.min_liquidity is not None and (item.liquidity_usd or 0.0) < query.min_liquidity:
                continue
            if query.orderbook_only and not item.enable_order_book:
                continue
            filtered.append(item)
        if query.sort == "volume_desc":
            filtered.sort(key=lambda item: item.volume_usd or 0.0, reverse=True)
        else:
            filtered.sort(key=lambda item: item.liquidity_usd or 0.0, reverse=True)
        return MarketCatalogBrowseResult(
            items=filtered[: query.limit],
            available_categories=["crypto", "politics"],
            applied_query=query,
        )
