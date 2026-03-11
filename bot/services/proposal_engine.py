from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from bot.config.models import Settings
from bot.domain.enums import ProposalStatus, TradeAction
from bot.domain.models import Market, ProbabilityEstimate, TradeProposal
from bot.policies.composite_policy import CompositePolicy
from bot.services.sizing import SizingEngine, SizingInput
from bot.utils.ids import new_id
from bot.utils.time import utc_now


@dataclass(slots=True)
class ProposalContext:
    market: Market
    probability: ProbabilityEstimate
    current_price: float
    open_positions: int
    unresolved_exposure_usd: float
    theme_exposure_usd: float
    order_type: str
    data_age_seconds: int
    thesis: list[str]
    risks: list[str]
    now: datetime
    edge: float
    proposed_size_usd: float = 0.0


class ProposalEngine:
    def __init__(self, sizing_engine: SizingEngine | None = None, composite_policy: CompositePolicy | None = None) -> None:
        self.sizing_engine = sizing_engine or SizingEngine()
        self.composite_policy = composite_policy or CompositePolicy()

    def create_proposal(self, settings: Settings, context: ProposalContext) -> TradeProposal:
        sizing = self.sizing_engine.size(
            settings,
            SizingInput(
                confidence=context.probability.confidence,
                min_confidence=settings.entry_rules.min_confidence,
                edge=context.edge,
                min_edge=settings.entry_rules.min_edge_pct,
                theme_exposure_usd=context.theme_exposure_usd,
                unresolved_exposure_usd=context.unresolved_exposure_usd,
                liquidity_usd=context.market.liquidity_usd,
            ),
        )
        evaluation_context = replace(context, proposed_size_usd=sizing.recommended_size_usd)
        policy_decision = self.composite_policy.evaluate(settings, evaluation_context)
        now = context.now
        status = (
            ProposalStatus.PENDING_MANUAL_CONFIRMATION
            if policy_decision.allowed
            else ProposalStatus.POLICY_REJECTED
        )
        return TradeProposal(
            proposal_id=new_id("proposal"),
            market_id=context.market.market_id,
            market_title=context.market.title,
            market_category=context.market.category,
            action=TradeAction.BUY if context.edge > 0 else TradeAction.SELL,
            side="yes" if context.edge > 0 else "no",
            market_price=context.current_price,
            fair_probability=context.probability.fair_probability,
            edge=context.edge,
            confidence=context.probability.confidence,
            model_agreement=context.probability.model_agreement,
            trusted_source_present=context.probability.trusted_source_present,
            source_types=context.probability.source_types,
            current_size_usd=sizing.recommended_size_usd,
            current_limit_price=round(context.current_price, 4),
            recommended_size_usd=sizing.recommended_size_usd,
            max_allowed_size_usd=sizing.max_allowed_size_usd,
            suggested_limit_price=round(context.current_price, 4),
            thesis=context.thesis + sizing.explanation,
            risks=context.risks,
            status=status,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(minutes=settings.approvals.proposal_ttl_minutes),
            policy_decision=policy_decision,
        )

    def create_default_context(
        self,
        market: Market,
        probability: ProbabilityEstimate,
        current_price: float,
    ) -> ProposalContext:
        now = utc_now()
        edge = probability.fair_probability - current_price
        return ProposalContext(
            market=market,
            probability=probability,
            current_price=current_price,
            open_positions=0,
            unresolved_exposure_usd=0.0,
            theme_exposure_usd=0.0,
            order_type="limit_only",
            data_age_seconds=0,
            thesis=["edge detected"],
            risks=["market risk"],
            now=now,
            edge=edge,
        )
