from __future__ import annotations

import asyncio
import argparse
import json
import os
from pathlib import Path

from bot.bootstrap import build_app_container, build_diagnostics_bootstrap, load_app_settings
from bot.cli.presenter import (
    analytics_summary_lines,
    alert_lines,
    audit_lines,
    decision_review_lines,
    event_catalog_lines,
    digest_lines,
    execution_evaluation_lines,
    execution_timeline_lines,
    execution_history_lines,
    outcome_analysis_lines,
    saved_view_lines,
    intent_detail_lines,
    intent_summary_line,
    latest_lookup_lines,
    market_data_lines,
    latest_execution_lines,
    list_header_lines,
    market_catalog_lines,
    market_opportunity_alert_lines,
    market_opportunity_lines,
    opportunity_draft_lines,
    proposal_detail_lines,
    polymarket_diagnostics_lines,
    probability_drift_lines,
    proposal_summary_line,
    probability_snapshot_lines,
    research_summary_lines,
    review_lines,
    runtime_safety_lines,
    slice_items,
    simulation_summary_lines,
    sort_items,
    watchlist_lines,
)
from bot.demo.seed import seed_demo_data
from bot.domain.enums import AlertState, WatchTargetType
from bot.services.market_catalog import MarketCatalogService
from bot.services.market_opportunity_scanner import MarketOpportunityScannerService
from bot.services.opportunity_proposal_bridge import OpportunityProposalBridgeService
from bot.services.polymarket_diagnostics import PolymarketDiagnosticsService
from bot.services.market_sync import LiveMarketDataService
from bot.services.realtime_market_feed import RealtimeMarketFeedService
from bot.services.runtime_safety import build_runtime_safety_snapshot
from bot.ui import serve_ui
from bot.telegram.auth import TelegramOperatorAuth
from bot.telegram.bot_app import build_telegram_bot_app
from bot.telegram.router import TelegramRouter


def _catalog_scope_to_flags(scope: str) -> tuple[bool, bool]:
    if scope == "active":
        return True, False
    if scope == "closed":
        return False, True
    if scope == "all":
        return True, True
    raise ValueError(f"Unsupported catalog scope: {scope}")


def _add_list_options(parser: argparse.ArgumentParser, default_sort: str = "updated_desc") -> None:
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--sort",
        choices=["updated_desc", "updated_asc", "created_desc", "created_asc", "status"],
        default=default_sort,
    )


def _print_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)


def _resolve_database_path() -> Path:
    database_url = os.getenv("BOT_DATABASE_URL")
    if not database_url:
        return Path("bot.db")
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    raise ValueError("BOT_DATABASE_URL must use sqlite:///...")


def _require_password_from_env(env_name: str) -> str:
    password = os.getenv(env_name)
    if not password:
        raise ValueError(f"Environment variable {env_name} is required and must be non-empty.")
    return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot")
    parser.add_argument("--config-dir", default=str(Path("config")))
    parser.add_argument("--profile", default="balanced")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run")
    subparsers.add_parser("scan")

    proposals = subparsers.add_parser("proposals")
    proposals_sub = proposals.add_subparsers(dest="proposals_command")
    proposals_list = proposals_sub.add_parser("list")
    proposals_list.add_argument("--scope", choices=["all", "active", "approved"], default="all")
    _add_list_options(proposals_list)
    show = proposals_sub.add_parser("show")
    show.add_argument("id")
    proposals_sub.add_parser("latest-approved")
    proposal_probability = proposals_sub.add_parser("probability")
    proposal_probability.add_argument("id")
    proposal_compare = proposals_sub.add_parser("compare")
    proposal_compare.add_argument("id")
    proposal_decision_review = proposals_sub.add_parser("decision-review")
    proposal_decision_review.add_argument("id")
    proposal_execution_evaluation = proposals_sub.add_parser("execution-evaluation")
    proposal_execution_evaluation.add_argument("id")
    proposal_research = proposals_sub.add_parser("research")
    proposal_research.add_argument("id")
    reviews = proposals_sub.add_parser("reviews")
    reviews.add_argument("id")
    audits = proposals_sub.add_parser("audits")
    audits.add_argument("id")
    approve = proposals_sub.add_parser("approve")
    approve.add_argument("id")
    reject = proposals_sub.add_parser("reject")
    reject.add_argument("id")
    edit_size = proposals_sub.add_parser("edit-size")
    edit_size.add_argument("id")
    edit_size.add_argument("amount", type=float)
    edit_price = proposals_sub.add_parser("edit-price")
    edit_price.add_argument("id")
    edit_price.add_argument("price", type=float)

    positions = subparsers.add_parser("positions")
    positions_sub = positions.add_subparsers(dest="positions_command")
    positions_sub.add_parser("list")
    close = positions_sub.add_parser("close")
    close.add_argument("id")

    config = subparsers.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command")
    config_sub.add_parser("validate")

    safety = subparsers.add_parser("safety")
    safety_sub = safety.add_subparsers(dest="safety_command")
    safety_sub.add_parser("pause")
    safety_sub.add_parser("resume")
    safety_sub.add_parser("kill-switch")
    safety_sub.add_parser("inspect")

    intents = subparsers.add_parser("intents")
    intents_sub = intents.add_subparsers(dest="intents_command")
    intents_list = intents_sub.add_parser("list")
    intents_list.add_argument("--scope", choices=["all", "active", "terminal"], default="all")
    _add_list_options(intents_list)
    intent_show = intents_sub.add_parser("show")
    intent_show.add_argument("id")
    intent_reviews = intents_sub.add_parser("reviews")
    intent_reviews.add_argument("id")
    intent_audits = intents_sub.add_parser("audits")
    intent_audits.add_argument("id")
    intent_simulate = intents_sub.add_parser("simulate")
    intent_simulate.add_argument("id")
    intent_simulate.add_argument("--best-bid", type=float)
    intent_simulate.add_argument("--best-ask", type=float)
    intent_simulate.add_argument("--ttl-ms", type=int)
    intent_simulate.add_argument("--cancel-after-ms", type=int)
    intent_simulate.add_argument("--base-latency-ms", type=int)
    intent_executions = intents_sub.add_parser("executions")
    intent_executions.add_argument("id")
    intent_timeline = intents_sub.add_parser("timeline")
    intent_timeline.add_argument("id")
    intent_evaluate = intents_sub.add_parser("evaluate")
    intent_evaluate.add_argument("id")
    intent_summary = intents_sub.add_parser("simulation-summary")
    intent_summary.add_argument("--intent-id")
    intents_sub.add_parser("latest-simulated")
    latest = intents_sub.add_parser("latest-for-proposal")
    latest.add_argument("proposal_id")
    intents_sub.add_parser("latest-terminal")

    health = subparsers.add_parser("health")
    health_sub = health.add_subparsers(dest="health_command")
    health_sub.add_parser("inspect")

    portfolio = subparsers.add_parser("portfolio")
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command")
    portfolio_summary = portfolio_sub.add_parser("summary")
    portfolio_summary.add_argument("--since-hours", type=int)

    session = subparsers.add_parser("session")
    session_sub = session.add_subparsers(dest="session_command")
    session_summary = session_sub.add_parser("summary")
    session_summary.add_argument("--since-hours", type=int)

    diagnostics = subparsers.add_parser("diagnostics")
    diagnostics_sub = diagnostics.add_subparsers(dest="diagnostics_command")
    diagnostics_sub.add_parser("polymarket")

    auth = subparsers.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="auth_command")
    auth_set_password = auth_sub.add_parser("set-password")
    auth_set_password.add_argument("--username", default="osokolin")
    auth_set_password.add_argument("--password-env", default="BOT_UI_PASSWORD")

    watchlist = subparsers.add_parser("watchlist")
    watchlist_sub = watchlist.add_subparsers(dest="watchlist_command")
    watchlist_add = watchlist_sub.add_parser("add")
    watchlist_add.add_argument("--type", choices=["market", "proposal", "intent"], required=True)
    watchlist_add.add_argument("--id", required=True)
    watchlist_add.add_argument("--label")
    watchlist_remove = watchlist_sub.add_parser("remove")
    watchlist_remove.add_argument("--type", choices=["market", "proposal", "intent"], required=True)
    watchlist_remove.add_argument("--id", required=True)
    watchlist_list = watchlist_sub.add_parser("list")
    watchlist_list.add_argument("--type", choices=["market", "proposal", "intent"])

    alerts = subparsers.add_parser("alerts")
    alerts_sub = alerts.add_subparsers(dest="alerts_command")
    alerts_sub.add_parser("scan")
    alerts_opportunities = alerts_sub.add_parser("scan-opportunities")
    alerts_opportunities.add_argument("--limit", type=int, default=200)
    alerts_list = alerts_sub.add_parser("list")
    alerts_list.add_argument("--watchlist-only", action="store_true")
    alerts_list.add_argument("--state", choices=["open", "acknowledged", "dismissed", "resolved"])
    alert_ack = alerts_sub.add_parser("acknowledge")
    alert_ack.add_argument("id")
    alert_dismiss = alerts_sub.add_parser("dismiss")
    alert_dismiss.add_argument("id")
    alert_resolve = alerts_sub.add_parser("resolve")
    alert_resolve.add_argument("id")

    markets = subparsers.add_parser("markets")
    markets_sub = markets.add_subparsers(dest="markets_command")
    market_probability = markets_sub.add_parser("probability")
    market_probability.add_argument("id")
    market_compare = markets_sub.add_parser("compare")
    market_compare.add_argument("id")
    market_decision_review = markets_sub.add_parser("decision-review")
    market_decision_review.add_argument("id")
    market_research = markets_sub.add_parser("research")
    market_research.add_argument("id")
    market_live = markets_sub.add_parser("live")
    market_live.add_argument("id")
    market_live.add_argument("--refresh", action="store_true")
    market_catalog = markets_sub.add_parser("catalog")
    market_catalog.add_argument("--limit", type=int, default=20)
    market_catalog.add_argument("--scope", choices=["active", "closed", "all"], default="active")
    market_scan = markets_sub.add_parser("scan")
    market_scan.add_argument("--min-edge", type=float)
    market_scan.add_argument("--min-liquidity", type=float)
    market_scan.add_argument("--limit", type=int, default=20)
    market_draft = markets_sub.add_parser("draft-opportunities")
    market_draft.add_argument("--min-edge", type=float)
    market_draft.add_argument("--min-liquidity", type=float)
    market_draft.add_argument("--limit", type=int, default=20)
    market_cache = markets_sub.add_parser("cache")
    market_cache.add_argument("id")
    market_stream = markets_sub.add_parser("stream-once")
    market_stream.add_argument("id")

    events = subparsers.add_parser("events")
    events_sub = events.add_subparsers(dest="events_command")
    event_catalog = events_sub.add_parser("catalog")
    event_catalog.add_argument("--limit", type=int, default=20)
    event_catalog.add_argument("--scope", choices=["active", "closed", "all"], default="active")

    analysis = subparsers.add_parser("analysis")
    analysis_sub = analysis.add_subparsers(dest="analysis_command")
    analysis_outcomes = analysis_sub.add_parser("outcomes")
    analysis_outcomes.add_argument(
        "--group-by",
        choices=["market", "category", "source_type", "confidence_band", "verdict_type"],
        default="market",
    )
    analysis_outcomes.add_argument("--since-hours", type=int)
    analysis_learning = analysis_sub.add_parser("learning-summary")
    analysis_learning.add_argument(
        "--group-by",
        choices=["market", "category", "source_type", "confidence_band", "verdict_type"],
        default="category",
    )
    analysis_learning.add_argument("--since-hours", type=int)
    analysis_latest = analysis_sub.add_parser("latest")
    analysis_latest.add_argument("--scope", choices=["outcomes", "learning_summary"], default="outcomes")
    analysis_latest.add_argument(
        "--group-by",
        choices=["market", "category", "source_type", "confidence_band", "verdict_type"],
        default="market",
    )

    views = subparsers.add_parser("views")
    views_sub = views.add_subparsers(dest="views_command")
    view_save = views_sub.add_parser("save")
    view_save.add_argument("--name", required=True)
    view_save.add_argument(
        "--kind",
        choices=["proposals_list", "intents_list", "alerts_list", "analysis_outcomes", "analysis_learning"],
        required=True,
    )
    view_save.add_argument("--params", required=True)
    views_sub.add_parser("list")
    view_show = views_sub.add_parser("show")
    view_show.add_argument("name")
    view_run = views_sub.add_parser("run")
    view_run.add_argument("name")

    export = subparsers.add_parser("export")
    export_sub = export.add_subparsers(dest="export_command")
    export_review = export_sub.add_parser("decision-review")
    export_review.add_argument("--proposal-id", required=True)
    export_review.add_argument("--output")
    export_eval = export_sub.add_parser("execution-evaluation")
    export_eval.add_argument("--proposal-id")
    export_eval.add_argument("--intent-id")
    export_eval.add_argument("--output")
    export_analysis = export_sub.add_parser("outcome-analysis")
    export_analysis.add_argument("--scope", choices=["outcomes", "learning_summary"], default="outcomes")
    export_analysis.add_argument(
        "--group-by",
        choices=["market", "category", "source_type", "confidence_band", "verdict_type"],
        default="market",
    )
    export_analysis.add_argument("--since-hours", type=int)
    export_analysis.add_argument("--output")

    digest = subparsers.add_parser("digest")
    digest_sub = digest.add_subparsers(dest="digest_command")
    digest_daily = digest_sub.add_parser("daily")
    digest_daily.add_argument("--since-hours", type=int, default=24)
    digest_session = digest_sub.add_parser("session")
    digest_session.add_argument("--since-hours", type=int, default=8)

    demo = subparsers.add_parser("demo")
    demo_sub = demo.add_subparsers(dest="demo_command")
    demo_sub.add_parser("seed")

    ui = subparsers.add_parser("ui")
    ui_sub = ui.add_subparsers(dest="ui_command")
    ui_serve = ui_sub.add_parser("serve")
    ui_serve.add_argument("--host", default="127.0.0.1")
    ui_serve.add_argument("--port", type=int, default=8080)

    telegram = subparsers.add_parser("telegram")
    telegram_sub = telegram.add_subparsers(dest="telegram_command")
    telegram_sub.add_parser("serve")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    settings = load_app_settings(Path(args.config_dir), profile=args.profile)
    if args.command == "diagnostics" and args.diagnostics_command == "polymarket":
        diagnostics_bootstrap = build_diagnostics_bootstrap(
            diagnostics_service_cls=PolymarketDiagnosticsService,
        )
        try:
            _print_lines(polymarket_diagnostics_lines(diagnostics_bootstrap.diagnostics_service.run()))
            return 0
        finally:
            diagnostics_bootstrap.close()
    container = build_app_container(
        settings,
        args.profile,
        _resolve_database_path(),
        market_data_service_cls=LiveMarketDataService,
        realtime_market_feed_service_cls=RealtimeMarketFeedService,
        market_catalog_service_cls=MarketCatalogService,
        scanner_service_cls=MarketOpportunityScannerService,
        diagnostics_service_cls=PolymarketDiagnosticsService,
        opportunity_bridge_service_cls=OpportunityProposalBridgeService,
    )
    try:
        market_data_service = container.market_data_service
        realtime_market_feed_service = container.realtime_market_feed_service
        market_catalog_service = container.market_catalog_service
        market_opportunity_alert_service = container.market_opportunity_alert_service
        market_opportunity_scanner = container.market_opportunity_scanner
        proposal_service = container.proposal_service
        opportunity_bridge_service = container.opportunity_bridge_service
        notifications_service = container.notifications_service
        execution_service = container.execution_service
        analytics_service = container.analytics_service
        decision_review_service = container.decision_review_service
        execution_evaluation_service = container.execution_evaluation_service
        outcome_analysis_service = container.outcome_analysis_service
        saved_view_service = container.saved_view_service
        reporting_service = container.reporting_service
        position_repository = container.position_repository
        telegram_operator_service = container.telegram_operator_service
        if args.command == "ui" and args.ui_command == "serve":
            serve_ui(container.dashboard_app(), args.host, args.port)
            return 0
        if args.command == "telegram" and args.telegram_command == "serve":
            if telegram_operator_service is None:
                raise ValueError("Telegram runtime is not configured")
            telegram_app = build_telegram_bot_app(
                TelegramRouter(
                    auth=TelegramOperatorAuth.from_env(),
                    operator_service=telegram_operator_service,
                ),
                telegram_operator_service,
            )
            try:
                telegram_app.serve_forever()
            finally:
                telegram_app.client.close()
            return 0
        if args.command == "demo" and args.demo_command == "seed":
            result = seed_demo_data(
                settings,
                proposal_service,
                execution_service,
                notifications_service,
                decision_review_service,
                execution_evaluation_service,
                outcome_analysis_service,
                saved_view_service,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "config" and args.config_command == "validate":
            print(f"config valid mode={settings.mode.value} profile={args.profile}")
            return 0
        if args.command == "auth" and args.auth_command == "set-password":
            if container.web_auth_service is None:
                raise ValueError("Web auth service is not configured")
            user = container.web_auth_service.set_password(
                args.username,
                _require_password_from_env(args.password_env),
            )
            print(f"password updated username={user.username}")
            return 0
        if args.command == "proposals" and args.proposals_command == "list":
            proposal_service.expire_stale()
            if args.scope == "active":
                proposals = proposal_service.list_active_proposals()
            elif args.scope == "approved":
                proposals = proposal_service.list_approved_proposals()
            else:
                proposals = proposal_service.list_proposals()
            proposals = sort_items(proposals, args.sort)
            page = slice_items(proposals, args.limit, args.offset)
            _print_lines(list_header_lines(args.scope, proposals, page, args.limit, args.offset, args.sort))
            for proposal in page:
                print(proposal_summary_line(proposal))
            return 0
        if args.command == "proposals" and args.proposals_command == "latest-approved":
            proposal = proposal_service.latest_approved_proposal()
            if proposal is None:
                print("no_approved_proposal")
            else:
                _print_lines(
                    latest_lookup_lines(
                        "latest_approved_proposal",
                        proposal.proposal_id,
                        proposal_summary_line(proposal),
                    )
                )
            return 0
        if args.command == "proposals" and args.proposals_command == "probability":
            _print_lines(probability_snapshot_lines(proposal_service.latest_probability_snapshot_for_proposal(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "compare":
            _print_lines(probability_drift_lines(proposal_service.compare_probability_snapshots_for_proposal(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "decision-review":
            _print_lines(decision_review_lines(decision_review_service.create_for_proposal(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "execution-evaluation":
            _print_lines(execution_evaluation_lines(execution_evaluation_service.evaluate_proposal(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "research":
            _print_lines(research_summary_lines(proposal_service.latest_probability_snapshot_for_proposal(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "show":
            proposal = proposal_service.latest_proposal_state(args.id)
            _print_lines(proposal_detail_lines(proposal))
            return 0
        if args.command == "proposals" and args.proposals_command == "reviews":
            _print_lines(review_lines(proposal_service.list_review_history(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "audits":
            _print_lines(audit_lines(proposal_service.list_audit_history(args.id)))
            return 0
        if args.command == "proposals" and args.proposals_command == "reject":
            proposal = proposal_service.reject(args.id, actor="cli")
            print(f"{proposal.proposal_id} {proposal.status.value}")
            return 0
        if args.command == "proposals" and args.proposals_command == "edit-size":
            proposal = proposal_service.edit_size(args.id, args.amount, actor="cli")
            print(f"{proposal.proposal_id} size={proposal.current_size_usd:.2f}")
            return 0
        if args.command == "proposals" and args.proposals_command == "edit-price":
            proposal = proposal_service.edit_price(args.id, args.price, actor="cli")
            print(f"{proposal.proposal_id} price={proposal.current_limit_price:.4f}")
            return 0
        if args.command == "proposals" and args.proposals_command == "approve":
            proposal = proposal_service.approve(
                settings,
                args.id,
                actor="cli",
                open_positions=0,
                unresolved_exposure_usd=0.0,
                theme_exposure_usd=0.0,
            )
            print(
                f"{proposal.proposal_id} {proposal.status.value} "
                f"market_price={proposal.market_price:.4f} limit={proposal.current_limit_price:.4f}"
            )
            return 0
        if args.command == "intents" and args.intents_command == "list":
            if args.scope == "active":
                intents = execution_service.list_active_intents()
            elif args.scope == "terminal":
                intents = execution_service.list_terminal_intents()
            else:
                intents = execution_service.list_all_intents()
            intents = sort_items(intents, args.sort)
            page = slice_items(intents, args.limit, args.offset)
            _print_lines(list_header_lines(args.scope, intents, page, args.limit, args.offset, args.sort))
            for intent in page:
                print(intent_summary_line(intent))
            return 0
        if args.command == "intents" and args.intents_command == "show":
            intent = execution_service.latest_intent_state(args.id)
            _print_lines(intent_detail_lines(intent))
            return 0
        if args.command == "intents" and args.intents_command == "latest-for-proposal":
            intent = execution_service.latest_active_intent(args.proposal_id)
            if intent is None:
                print("no_active_intent")
            else:
                _print_lines(latest_lookup_lines("latest_active_intent", intent.intent_id, intent_summary_line(intent)))
            return 0
        if args.command == "intents" and args.intents_command == "latest-terminal":
            intent = execution_service.latest_terminal_intent()
            if intent is None:
                print("no_terminal_intent")
            else:
                _print_lines(
                    latest_lookup_lines("latest_terminal_intent", intent.intent_id, intent_summary_line(intent))
                )
            return 0
        if args.command == "intents" and args.intents_command == "reviews":
            _print_lines(review_lines(execution_service.list_review_history(args.id)))
            return 0
        if args.command == "intents" and args.intents_command == "audits":
            _print_lines(audit_lines(execution_service.list_audit_history(args.id)))
            return 0
        if args.command == "intents" and args.intents_command == "simulate":
            outcome = execution_service.simulate_intent(
                args.id,
                actor="cli",
                best_bid=args.best_bid,
                best_ask=args.best_ask,
                ttl_ms=args.ttl_ms,
                cancel_after_ms=args.cancel_after_ms,
                base_latency_ms=args.base_latency_ms,
            )
            print(
                f"intent={args.id} stage={outcome.stage} accepted={outcome.accepted} "
                f"reference_price={outcome.reference_price:.4f} "
                f"best_bid={'-' if outcome.best_bid is None else f'{outcome.best_bid:.4f}'} "
                f"best_ask={'-' if outcome.best_ask is None else f'{outcome.best_ask:.4f}'} "
                f"simulated_price="
                f"{'-' if outcome.simulated_price is None else f'{outcome.simulated_price:.4f}'} "
                f"slippage_bps={'-' if outcome.slippage_bps is None else f'{outcome.slippage_bps:.2f}'} "
                f"latency_ms={'-' if outcome.latency_ms is None else outcome.latency_ms} "
                f"completion_reason={outcome.completion_reason or '-'}"
            )
            return 0
        if args.command == "intents" and args.intents_command == "executions":
            _print_lines(execution_history_lines(execution_service.list_execution_history(args.id)))
            return 0
        if args.command == "intents" and args.intents_command == "timeline":
            _print_lines(execution_timeline_lines(execution_service.list_execution_timeline(args.id)))
            return 0
        if args.command == "intents" and args.intents_command == "evaluate":
            _print_lines(execution_evaluation_lines(execution_evaluation_service.evaluate_intent(args.id)))
            return 0
        if args.command == "intents" and args.intents_command == "simulation-summary":
            if args.intent_id:
                _print_lines(simulation_summary_lines(execution_service.simulation_summary_for_intent(args.intent_id)))
            else:
                _print_lines(simulation_summary_lines(execution_service.simulation_summary_overall()))
            return 0
        if args.command == "intents" and args.intents_command == "latest-simulated":
            _print_lines(latest_execution_lines(execution_service.latest_simulated_execution_overall()))
            return 0
        if args.command == "safety" and args.safety_command == "inspect":
            snapshot = build_runtime_safety_snapshot(
                settings,
                args.profile,
                execution_service.execution_adapter,
                open_positions=position_repository.count_open(),
                unresolved_exposure_usd=position_repository.unresolved_exposure(),
            )
            _print_lines(runtime_safety_lines(snapshot, include_exposure=False))
            return 0
        if args.command == "health" and args.health_command == "inspect":
            snapshot = build_runtime_safety_snapshot(
                settings,
                args.profile,
                execution_service.execution_adapter,
                open_positions=position_repository.count_open(),
                unresolved_exposure_usd=position_repository.unresolved_exposure(),
            )
            _print_lines(runtime_safety_lines(snapshot, include_exposure=True))
            return 0
        if args.command == "portfolio" and args.portfolio_command == "summary":
            _print_lines(analytics_summary_lines(analytics_service.summarize("portfolio", args.since_hours)))
            return 0
        if args.command == "session" and args.session_command == "summary":
            _print_lines(analytics_summary_lines(analytics_service.summarize("session", args.since_hours)))
            return 0
        if args.command == "watchlist" and args.watchlist_command == "add":
            entry = notifications_service.add_watch(WatchTargetType(args.type), args.id, args.label)
            _print_lines(watchlist_lines([entry]))
            return 0
        if args.command == "watchlist" and args.watchlist_command == "remove":
            notifications_service.remove_watch(WatchTargetType(args.type), args.id)
            print(f"removed {args.type}:{args.id}")
            return 0
        if args.command == "watchlist" and args.watchlist_command == "list":
            target_type = None if args.type is None else WatchTargetType(args.type)
            _print_lines(watchlist_lines(notifications_service.list_watchlist(target_type)))
            return 0
        if args.command == "alerts" and args.alerts_command == "scan":
            _print_lines(alert_lines(notifications_service.scan()))
            return 0
        if args.command == "alerts" and args.alerts_command == "scan-opportunities":
            _print_lines(market_opportunity_alert_lines(market_opportunity_alert_service.scan(settings, limit=args.limit)))
            return 0
        if args.command == "alerts" and args.alerts_command == "list":
            state = None if args.state is None else AlertState(args.state)
            _print_lines(alert_lines(notifications_service.list_alerts(watchlist_only=args.watchlist_only, state=state)))
            return 0
        if args.command == "alerts" and args.alerts_command == "acknowledge":
            _print_lines(alert_lines([notifications_service.acknowledge_alert(args.id)]))
            return 0
        if args.command == "alerts" and args.alerts_command == "dismiss":
            _print_lines(alert_lines([notifications_service.dismiss_alert(args.id)]))
            return 0
        if args.command == "alerts" and args.alerts_command == "resolve":
            _print_lines(alert_lines([notifications_service.resolve_alert(args.id)]))
            return 0
        if args.command == "markets" and args.markets_command == "probability":
            _print_lines(probability_snapshot_lines(proposal_service.latest_probability_snapshot_for_market(args.id)))
            return 0
        if args.command == "markets" and args.markets_command == "compare":
            _print_lines(probability_drift_lines(proposal_service.compare_probability_snapshots_for_market(args.id)))
            return 0
        if args.command == "markets" and args.markets_command == "decision-review":
            _print_lines(decision_review_lines(decision_review_service.create_for_market(args.id)))
            return 0
        if args.command == "markets" and args.markets_command == "research":
            _print_lines(research_summary_lines(proposal_service.latest_probability_snapshot_for_market(args.id)))
            return 0
        if args.command == "markets" and args.markets_command == "live":
            _print_lines(market_data_lines(market_data_service.inspect_snapshot(args.id, refresh=args.refresh)))
            return 0
        if args.command == "markets" and args.markets_command == "catalog":
            active, closed = _catalog_scope_to_flags(args.scope)
            _print_lines(
                market_catalog_lines(
                    market_catalog_service.list_markets(limit=args.limit, active=active, closed=closed)
                )
            )
            return 0
        if args.command == "markets" and args.markets_command == "scan":
            _print_lines(
                market_opportunity_lines(
                    market_opportunity_scanner.scan(
                        settings,
                        min_edge=args.min_edge,
                        min_liquidity=args.min_liquidity,
                        limit=args.limit,
                    )
                )
            )
            return 0
        if args.command == "markets" and args.markets_command == "draft-opportunities":
            _print_lines(
                opportunity_draft_lines(
                    opportunity_bridge_service.draft_opportunities(
                        settings,
                        min_edge=args.min_edge,
                        min_liquidity=args.min_liquidity,
                        limit=args.limit,
                    )
                )
            )
            return 0
        if args.command == "markets" and args.markets_command == "cache":
            snapshot = market_data_service.latest_cached_snapshot(args.id)
            if snapshot is None:
                print("no_cached_market_snapshot")
            else:
                _print_lines(market_data_lines(snapshot))
            return 0
        if args.command == "markets" and args.markets_command == "stream-once":
            _print_lines(market_data_lines(asyncio.run(realtime_market_feed_service.refresh_from_websocket(args.id))))
            return 0
        if args.command == "events" and args.events_command == "catalog":
            active, closed = _catalog_scope_to_flags(args.scope)
            _print_lines(
                event_catalog_lines(
                    market_catalog_service.list_events(limit=args.limit, active=active, closed=closed)
                )
            )
            return 0
        if args.command == "analysis" and args.analysis_command == "outcomes":
            _print_lines(outcome_analysis_lines(outcome_analysis_service.summarize_outcomes(args.group_by, args.since_hours)))
            return 0
        if args.command == "analysis" and args.analysis_command == "learning-summary":
            _print_lines(outcome_analysis_lines(outcome_analysis_service.summarize_learning(args.group_by, args.since_hours)))
            return 0
        if args.command == "analysis" and args.analysis_command == "latest":
            snapshot = outcome_analysis_service.latest_snapshot(args.scope, args.group_by)
            if snapshot is None:
                print("no_analysis_snapshot")
            else:
                _print_lines(outcome_analysis_lines(snapshot))
            return 0
        if args.command == "views" and args.views_command == "save":
            saved = saved_view_service.save(args.name, args.kind, json.loads(args.params))
            _print_lines(saved_view_lines([saved]))
            return 0
        if args.command == "views" and args.views_command == "list":
            _print_lines(saved_view_lines(saved_view_service.list_all()))
            return 0
        if args.command == "views" and args.views_command == "show":
            saved = saved_view_service.get(args.name)
            _print_lines(saved_view_lines([] if saved is None else [saved]))
            return 0
        if args.command == "views" and args.views_command == "run":
            saved = saved_view_service.get(args.name)
            if saved is None:
                print("no_saved_view")
                return 0
            params = saved.params
            if saved.kind == "analysis_outcomes":
                _print_lines(outcome_analysis_lines(outcome_analysis_service.summarize_outcomes(params.get("group_by", "market"), params.get("since_hours"))))
            elif saved.kind == "analysis_learning":
                _print_lines(outcome_analysis_lines(outcome_analysis_service.summarize_learning(params.get("group_by", "category"), params.get("since_hours"))))
            elif saved.kind == "alerts_list":
                state = params.get("state")
                _print_lines(alert_lines(notifications_service.list_alerts(params.get("watchlist_only", False), None if state is None else AlertState(state))))
            elif saved.kind == "proposals_list":
                scope = params.get("scope", "all")
                proposals = proposal_service.list_proposals() if scope == "all" else (
                    proposal_service.list_active_proposals() if scope == "active" else proposal_service.list_approved_proposals()
                )
                proposals = sort_items(proposals, params.get("sort", "updated_desc"))
                page = slice_items(proposals, int(params.get("limit", 20)), int(params.get("offset", 0)))
                _print_lines(list_header_lines(scope, proposals, page, int(params.get("limit", 20)), int(params.get("offset", 0)), params.get("sort", "updated_desc")))
                for proposal in page:
                    print(proposal_summary_line(proposal))
            elif saved.kind == "intents_list":
                scope = params.get("scope", "all")
                intents = execution_service.list_all_intents() if scope == "all" else (
                    execution_service.list_active_intents() if scope == "active" else execution_service.list_terminal_intents()
                )
                intents = sort_items(intents, params.get("sort", "updated_desc"))
                page = slice_items(intents, int(params.get("limit", 20)), int(params.get("offset", 0)))
                _print_lines(list_header_lines(scope, intents, page, int(params.get("limit", 20)), int(params.get("offset", 0)), params.get("sort", "updated_desc")))
                for intent in page:
                    print(intent_summary_line(intent))
            return 0
        if args.command == "export" and args.export_command == "decision-review":
            print(reporting_service.write_export(reporting_service.export_decision_review(args.proposal_id), args.output))
            return 0
        if args.command == "export" and args.export_command == "execution-evaluation":
            print(reporting_service.write_export(reporting_service.export_execution_evaluation(args.proposal_id, args.intent_id), args.output))
            return 0
        if args.command == "export" and args.export_command == "outcome-analysis":
            print(reporting_service.write_export(reporting_service.export_outcome_analysis(args.scope, args.group_by, args.since_hours), args.output))
            return 0
        if args.command == "digest" and args.digest_command == "daily":
            _print_lines(digest_lines(reporting_service.build_digest("daily", args.since_hours)))
            return 0
        if args.command == "digest" and args.digest_command == "session":
            _print_lines(digest_lines(reporting_service.build_digest("session", args.since_hours)))
            return 0
    finally:
        container.close()
    print(f"command={args.command} mode={settings.mode.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
