from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from bot.config.models import Settings
from bot.domain.enums import SourceType, WatchTargetType
from bot.domain.models import Market, ProbabilityEstimate
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.operator_notifications import OperatorNotificationsService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.services.saved_views import SavedViewService
from bot.utils.time import utc_now


def seed_demo_data(
    settings: Settings,
    proposal_service: ProposalLifecycleService,
    execution_service: ExecutionPipelineService,
    notifications_service: OperatorNotificationsService,
    decision_review_service: DecisionReviewService,
    execution_evaluation_service: ExecutionEvaluationService,
    outcome_analysis_service: OutcomeAnalysisService,
    saved_view_service: SavedViewService,
) -> dict[str, object]:
    now = utc_now()
    primary_market = Market(
        market_id="demo_rates_2026",
        title="Will the Fed cut rates before year-end?",
        category="crypto",
        liquidity_usd=35000,
        spread_pct=0.01,
        resolution_time=now + timedelta(days=120),
        rules_text="Clear market rules.",
        rules_confidence=0.99,
        tags=["macro", "rates"],
        has_orderbook=True,
    )
    secondary_market = replace(
        primary_market,
        market_id="demo_inflation_2026",
        title="Will CPI print below consensus next release?",
        tags=["macro", "inflation"],
    )
    probability = ProbabilityEstimate(
        market_id=primary_market.market_id,
        fair_probability=0.72,
        confidence=0.9,
        model_agreement=3,
        trusted_source_present=True,
        source_types=[SourceType.OFFICIAL, SourceType.MAJOR_MEDIA],
        key_factors=["policy easing", "soft labor data"],
        source_count=2,
        confidence_components={"model": 0.91, "liquidity": 1.0, "spread": 0.99},
    )

    pending = proposal_service.create(
        settings,
        proposal_service.proposal_engine.create_default_context(
            secondary_market,
            replace(probability, market_id=secondary_market.market_id),
            0.46,
        ),
    )
    proposal_service.proposal_repository.save(
        replace(pending, expires_at=utc_now() + timedelta(minutes=5), updated_at=utc_now())
    )

    proposal = proposal_service.create(
        settings,
        proposal_service.proposal_engine.create_default_context(primary_market, probability, 0.45),
    )
    original_snapshot_provider = proposal_service.snapshot_provider
    proposal_service.snapshot_provider = None
    try:
        approved = proposal_service.approve(
            settings,
            proposal.proposal_id,
            actor="demo-seed",
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            market=primary_market,
            probability=replace(
                probability,
                fair_probability=0.69,
                confidence=0.92,
                source_count=3,
                key_factors=["policy easing", "soft labor data", "disinflation trend"],
            ),
            data_age_seconds=0,
        )
    finally:
        proposal_service.snapshot_provider = original_snapshot_provider
    intent = execution_service.create_order_intent(approved)
    execution_service.prepare_submission(intent.intent_id)
    execution_service.simulate_intent(intent.intent_id, actor="demo-seed")

    notifications_service.add_watch(WatchTargetType.PROPOSAL, pending.proposal_id, "ttl watch")
    notifications_service.add_watch(WatchTargetType.MARKET, primary_market.market_id, "macro market")
    alerts = notifications_service.scan()

    decision_review_service.create_for_proposal(approved.proposal_id)
    decision_review_service.create_for_market(approved.market_id)
    evaluation = execution_evaluation_service.evaluate_proposal(approved.proposal_id)
    outcome_analysis_service.summarize_outcomes("market")
    outcome_analysis_service.summarize_learning("category")

    saved_view_service.save(
        "demo-approved-proposals",
        "proposals_list",
        {"scope": "approved", "limit": 10, "offset": 0, "sort": "updated_desc"},
    )
    saved_view_service.save(
        "demo-open-alerts",
        "alerts_list",
        {"state": "open", "watchlist_only": False},
    )

    return {
        "pending_proposal_id": pending.proposal_id,
        "approved_proposal_id": approved.proposal_id,
        "intent_id": intent.intent_id,
        "evaluation_id": evaluation.evaluation_id,
        "alert_count": len(alerts),
        "saved_view_count": len(saved_view_service.list_all()),
    }
