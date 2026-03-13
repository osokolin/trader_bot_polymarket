from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from bot.adapters.polymarket.clob_client import ClobMarketDataClient, PolymarketClient, PolymarketOrderBookAdapter
from bot.adapters.polymarket.gamma_client import GammaApiClient, PolymarketMarketMetadataAdapter
from bot.adapters.polymarket.trading import PaperExecutionAdapter, SemiAutoExecutionAdapter
from bot.adapters.polymarket.websocket_market import PublicMarketWebSocketClient
from bot.config.loader import load_settings
from bot.config.models import Settings
from bot.services.analytics import AnalyticsService
from bot.services.approval_snapshot_provider import PolymarketApprovalSnapshotProvider
from bot.services.audit_log import AuditLogService
from bot.services.decision_inbox import DecisionInboxService
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.inbox_handlers import build_default_inbox_handlers
from bot.services.market_catalog import MarketCatalogService
from bot.services.market_opportunity_alerts import MarketOpportunityAlertService
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.market_research import MarketResearchService
from bot.services.market_sync import LiveMarketDataService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.opportunity_proposal_bridge import OpportunityProposalBridgeService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsService
from bot.services.probability_engine import EdgeAdjustedProbabilityProvider
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.realtime_market_feed import RealtimeMarketFeedService
from bot.services.reporting import ReportingService
from bot.services.saved_views import SavedViewService
from bot.services.telegram_operator_service import TelegramOperatorService
from bot.services.web_auth import WebAuthService
from bot.storage.db import Database
from bot.storage.repositories import (
    AlertRepository,
    AuditRepository,
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    MarketDataSnapshotRepository,
    OperatorActionRequestRepository,
    OrderIntentRepository,
    OutcomeAnalysisRepository,
    PositionRepository,
    ProbabilitySnapshotRepository,
    ProposalRepository,
    SavedViewRepository,
    WebAuthRepository,
    WatchlistRepository,
)
from bot.ui import AuthenticatedOperatorDashboardApp, OperatorDashboardApp, OperatorDashboardServices


@dataclass(slots=True)
class DiagnosticsBootstrap:
    polymarket_client: PolymarketClient
    gamma_client: GammaApiClient
    diagnostics_service: PolymarketDiagnosticsService

    def close(self) -> None:
        self.gamma_client.close()
        self.polymarket_client.close()


def _ui_cookie_secure() -> bool:
    explicit = os.getenv("BOT_UI_SECURE_COOKIES")
    if explicit is not None:
        return explicit.lower() not in {"0", "false", "no"}
    return os.getenv("BOT_ENV", "dev") != "dev"


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    profile: str
    database: Database
    connection: object
    polymarket_client: PolymarketClient | None
    gamma_client: GammaApiClient | None
    market_data_service: LiveMarketDataService | None
    realtime_market_feed_service: RealtimeMarketFeedService | None
    market_catalog_service: MarketCatalogService | None
    market_research_service: MarketResearchService | None
    market_opportunity_alert_service: MarketOpportunityAlertService | None
    market_opportunity_scanner: MarketOpportunityScannerService | None
    proposal_service: ProposalLifecycleService
    opportunity_bridge_service: OpportunityProposalBridgeService | None
    notifications_service: OperatorNotificationsService
    execution_service: ExecutionPipelineService
    analytics_service: AnalyticsService
    decision_review_service: DecisionReviewService
    decision_inbox_service: DecisionInboxService | None
    execution_evaluation_service: ExecutionEvaluationService
    outcome_analysis_service: OutcomeAnalysisService
    saved_view_service: SavedViewService
    reporting_service: ReportingService
    position_repository: PositionRepository
    diagnostics_service: PolymarketDiagnosticsService | None
    telegram_operator_service: TelegramOperatorService | None
    web_auth_service: WebAuthService | None

    def dashboard_services(self) -> OperatorDashboardServices:
        return OperatorDashboardServices(
            proposal_service=self.proposal_service,
            execution_service=self.execution_service,
            notifications_service=self.notifications_service,
            decision_review_service=self.decision_review_service,
            execution_evaluation_service=self.execution_evaluation_service,
            outcome_analysis_service=self.outcome_analysis_service,
            saved_view_service=self.saved_view_service,
            reporting_service=self.reporting_service,
            market_data_service=self.market_data_service,
            market_catalog_service=self.market_catalog_service,
            market_research_service=self.market_research_service,
        )

    def dashboard_app(self) -> OperatorDashboardApp:
        if self.web_auth_service is None:
            return OperatorDashboardApp(self.dashboard_services())
        return AuthenticatedOperatorDashboardApp(self.dashboard_services(), self.web_auth_service)

    def close(self) -> None:
        if hasattr(self.connection, "close"):
            self.connection.close()
        if self.gamma_client is not None:
            self.gamma_client.close()
        if self.polymarket_client is not None:
            self.polymarket_client.close()


def load_app_settings(config_dir: Path, profile: str = "balanced") -> Settings:
    return load_settings(config_dir, profile=profile)


def build_diagnostics_bootstrap(
    diagnostics_service_cls: type[PolymarketDiagnosticsService] = PolymarketDiagnosticsService,
) -> DiagnosticsBootstrap:
    polymarket_client = PolymarketClient()
    gamma_client = GammaApiClient()
    diagnostics_service = diagnostics_service_cls(
        gamma_client=gamma_client,
        clob_client=ClobMarketDataClient(http_client=polymarket_client.http_client),
        websocket_client=PublicMarketWebSocketClient(),
    )
    return DiagnosticsBootstrap(
        polymarket_client=polymarket_client,
        gamma_client=gamma_client,
        diagnostics_service=diagnostics_service,
    )


def build_app_container(
    settings: Settings,
    profile: str,
    database_path: Path,
    *,
    include_market_runtime: bool = True,
    include_telegram_runtime: bool = True,
    execution_adapter: object | None = None,
    paper_execution_adapter: object | None = None,
    market_data_service_cls: type[LiveMarketDataService] = LiveMarketDataService,
    realtime_market_feed_service_cls: type[RealtimeMarketFeedService] = RealtimeMarketFeedService,
    market_catalog_service_cls: type[MarketCatalogService] = MarketCatalogService,
    scanner_service_cls: type[MarketOpportunityScannerService] = MarketOpportunityScannerService,
    market_opportunity_alert_service_cls: type[MarketOpportunityAlertService] = MarketOpportunityAlertService,
    diagnostics_service_cls: type[PolymarketDiagnosticsService] = PolymarketDiagnosticsService,
    opportunity_bridge_service_cls: type[OpportunityProposalBridgeService] = OpportunityProposalBridgeService,
) -> AppContainer:
    database = Database(database_path)
    database.initialize()
    connection = database.connect()

    proposal_repository = ProposalRepository(connection)
    intent_repository = OrderIntentRepository(connection)
    audit_log = AuditLogService(AuditRepository(connection))
    probability_snapshot_repository = ProbabilitySnapshotRepository(connection)
    alert_repository = AlertRepository(connection)
    watchlist_repository = WatchlistRepository(connection)
    decision_review_repository = DecisionReviewRepository(connection)
    execution_evaluation_repository = ExecutionEvaluationRepository(connection)
    outcome_analysis_repository = OutcomeAnalysisRepository(connection)
    saved_view_repository = SavedViewRepository(connection)
    position_repository = PositionRepository(connection)

    polymarket_client: PolymarketClient | None = None
    gamma_client: GammaApiClient | None = None
    market_data_service: LiveMarketDataService | None = None
    realtime_market_feed_service: RealtimeMarketFeedService | None = None
    market_catalog_service: MarketCatalogService | None = None
    market_research_service: MarketResearchService | None = None
    market_opportunity_alert_service: MarketOpportunityAlertService | None = None
    market_opportunity_scanner: MarketOpportunityScannerService | None = None
    diagnostics_service: PolymarketDiagnosticsService | None = None
    opportunity_bridge_service: OpportunityProposalBridgeService | None = None
    decision_inbox_service: DecisionInboxService | None = None
    telegram_operator_service: TelegramOperatorService | None = None
    web_auth_service: WebAuthService | None = None

    if include_market_runtime:
        polymarket_client = PolymarketClient()
        gamma_client = GammaApiClient()
        market_data_service = market_data_service_cls(
            PolymarketMarketMetadataAdapter(gamma_client),
            PolymarketOrderBookAdapter(ClobMarketDataClient(http_client=polymarket_client.http_client)),
            MarketDataSnapshotRepository(connection),
        )
        realtime_market_feed_service = realtime_market_feed_service_cls(
            market_data_service,
            PublicMarketWebSocketClient(),
            stale_after_seconds=market_data_service.stale_after_seconds,
        )
        market_catalog_service = market_catalog_service_cls(gamma_client)
        market_opportunity_scanner = scanner_service_cls(
            market_catalog_service=market_catalog_service,
            market_data_service=market_data_service,
        )
        diagnostics_service = diagnostics_service_cls(
            gamma_client=gamma_client,
            clob_client=ClobMarketDataClient(http_client=polymarket_client.http_client),
            websocket_client=PublicMarketWebSocketClient(),
        )

    proposal_service = ProposalLifecycleService(
        proposal_repository,
        audit_log,
        snapshot_provider=(
            None
            if market_data_service is None
            else PolymarketApprovalSnapshotProvider(market_data_service, EdgeAdjustedProbabilityProvider())
        ),
        probability_snapshot_repository=probability_snapshot_repository,
    )
    notifications_service = OperatorNotificationsService(
        watchlist_repository,
        alert_repository,
        proposal_repository,
        intent_repository,
    )
    execution_service = ExecutionPipelineService(
        settings,
        execution_adapter if execution_adapter is not None else SemiAutoExecutionAdapter(),
        intent_repository,
        audit_log,
        paper_execution_adapter=paper_execution_adapter if paper_execution_adapter is not None else PaperExecutionAdapter(),
        notifications_service=notifications_service,
    )
    analytics_service = AnalyticsService(proposal_service, execution_service)
    decision_review_service = DecisionReviewService(
        proposal_service,
        execution_service,
        decision_review_repository,
    )
    execution_evaluation_service = ExecutionEvaluationService(
        proposal_service,
        execution_service,
        execution_evaluation_repository,
    )
    outcome_analysis_service = OutcomeAnalysisService(
        proposal_service,
        decision_review_repository,
        execution_evaluation_repository,
        outcome_analysis_repository,
    )
    market_research_service = MarketResearchService(
        proposal_service,
        decision_review_service,
        execution_evaluation_service,
        outcome_analysis_service,
    )
    saved_view_service = SavedViewService(saved_view_repository)
    reporting_service = ReportingService(
        decision_review_repository,
        execution_evaluation_service,
        outcome_analysis_service,
        notifications_service,
        analytics_service,
    )
    web_auth_service = WebAuthService(
        WebAuthRepository(connection),
        audit_log,
        cookie_secure=_ui_cookie_secure(),
    )

    if market_opportunity_scanner is not None:
        opportunity_bridge_service = opportunity_bridge_service_cls(
            scanner_service=market_opportunity_scanner,
            proposal_service=proposal_service,
        )
    if market_catalog_service is not None and market_research_service is not None:
        market_opportunity_alert_service = market_opportunity_alert_service_cls(
            market_catalog_service=market_catalog_service,
            notifications_service=notifications_service,
            market_research_service=market_research_service,
        )

    if include_telegram_runtime and diagnostics_service is not None and market_opportunity_scanner is not None:
        decision_inbox_service = DecisionInboxService(
            settings=settings,
            repository=OperatorActionRequestRepository(connection),
            audit_log=audit_log,
            proposal_service=proposal_service,
            decision_review_service=decision_review_service,
            notifications_service=notifications_service,
            diagnostics_service=diagnostics_service,
            handlers=build_default_inbox_handlers(
                settings=settings,
                proposal_service=proposal_service,
                decision_review_service=decision_review_service,
                notifications_service=notifications_service,
                diagnostics_service=diagnostics_service,
            ),
        )
        telegram_operator_service = TelegramOperatorService(
            settings=settings,
            profile=profile,
            execution_adapter=execution_service.execution_adapter,
            audit_log=audit_log,
            proposal_service=proposal_service,
            decision_review_service=decision_review_service,
            decision_inbox_service=decision_inbox_service,
            notifications_service=notifications_service,
            scanner_service=market_opportunity_scanner,
            market_opportunity_alert_service=market_opportunity_alert_service,
            diagnostics_service=diagnostics_service,
        )

    return AppContainer(
        settings=settings,
        profile=profile,
        database=database,
        connection=connection,
        polymarket_client=polymarket_client,
        gamma_client=gamma_client,
        market_data_service=market_data_service,
        realtime_market_feed_service=realtime_market_feed_service,
        market_catalog_service=market_catalog_service,
        market_research_service=market_research_service,
        market_opportunity_alert_service=market_opportunity_alert_service,
        market_opportunity_scanner=market_opportunity_scanner,
        proposal_service=proposal_service,
        opportunity_bridge_service=opportunity_bridge_service,
        notifications_service=notifications_service,
        execution_service=execution_service,
        analytics_service=analytics_service,
        decision_review_service=decision_review_service,
        decision_inbox_service=decision_inbox_service,
        execution_evaluation_service=execution_evaluation_service,
        outcome_analysis_service=outcome_analysis_service,
        saved_view_service=saved_view_service,
        reporting_service=reporting_service,
        position_repository=position_repository,
        diagnostics_service=diagnostics_service,
        telegram_operator_service=telegram_operator_service,
        web_auth_service=web_auth_service,
    )


def build_app_container_from_config(
    config_dir: Path,
    profile: str,
    database_path: Path,
    *,
    include_market_runtime: bool = True,
    include_telegram_runtime: bool = True,
    execution_adapter: object | None = None,
    paper_execution_adapter: object | None = None,
    market_data_service_cls: type[LiveMarketDataService] = LiveMarketDataService,
    realtime_market_feed_service_cls: type[RealtimeMarketFeedService] = RealtimeMarketFeedService,
    market_catalog_service_cls: type[MarketCatalogService] = MarketCatalogService,
    scanner_service_cls: type[MarketOpportunityScannerService] = MarketOpportunityScannerService,
    market_opportunity_alert_service_cls: type[MarketOpportunityAlertService] = MarketOpportunityAlertService,
    diagnostics_service_cls: type[PolymarketDiagnosticsService] = PolymarketDiagnosticsService,
    opportunity_bridge_service_cls: type[OpportunityProposalBridgeService] = OpportunityProposalBridgeService,
) -> AppContainer:
    settings = load_app_settings(config_dir, profile)
    return build_app_container(
        settings,
        profile,
        database_path,
        include_market_runtime=include_market_runtime,
        include_telegram_runtime=include_telegram_runtime,
        execution_adapter=execution_adapter,
        paper_execution_adapter=paper_execution_adapter,
        market_data_service_cls=market_data_service_cls,
        realtime_market_feed_service_cls=realtime_market_feed_service_cls,
        market_catalog_service_cls=market_catalog_service_cls,
        scanner_service_cls=scanner_service_cls,
        market_opportunity_alert_service_cls=market_opportunity_alert_service_cls,
        diagnostics_service_cls=diagnostics_service_cls,
        opportunity_bridge_service_cls=opportunity_bridge_service_cls,
    )
