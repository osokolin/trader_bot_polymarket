from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot.domain.models import (
    DecisionReviewSnapshot,
    ExecutionEvaluationSnapshot,
    OutcomeAnalysisGroup,
    ProbabilityDrift,
    ProbabilitySnapshot,
    TradeProposal,
)
from bot.services.decision_review import DecisionReviewService
from bot.services.execution_evaluation import ExecutionEvaluationService
from bot.services.outcome_analysis import OutcomeAnalysisService
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService


@dataclass(slots=True)
class MarketAnalysisReference:
    snapshot_id: str
    scope: str
    summary: str
    group: OutcomeAnalysisGroup
    created_at: datetime


@dataclass(slots=True)
class MarketProposalContext:
    market_id: str
    proposals: list[TradeProposal]
    latest_proposal: TradeProposal | None
    latest_decision_review: DecisionReviewSnapshot | None

    @property
    def proposal_count(self) -> int:
        return len(self.proposals)


@dataclass(slots=True)
class MarketResearchContext:
    market_id: str
    related_proposals: list[TradeProposal]
    latest_probability_snapshot: ProbabilitySnapshot | None
    probability_drift: ProbabilityDrift | None
    latest_decision_review: DecisionReviewSnapshot | None
    latest_execution_evaluation: ExecutionEvaluationSnapshot | None
    latest_outcome_analysis: MarketAnalysisReference | None
    latest_learning_analysis: MarketAnalysisReference | None

    @property
    def has_artifacts(self) -> bool:
        return any(
            item is not None
            for item in (
                self.latest_probability_snapshot,
                self.latest_decision_review,
                self.latest_execution_evaluation,
                self.latest_outcome_analysis,
                self.latest_learning_analysis,
            )
        ) or bool(self.related_proposals)


class MarketResearchService:
    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        decision_review_service: DecisionReviewService,
        execution_evaluation_service: ExecutionEvaluationService,
        outcome_analysis_service: OutcomeAnalysisService,
    ) -> None:
        self.proposal_service = proposal_service
        self.decision_review_service = decision_review_service
        self.execution_evaluation_service = execution_evaluation_service
        self.outcome_analysis_service = outcome_analysis_service

    def get_market_research_context(self, market_id: str) -> MarketResearchContext:
        proposal_context = self.get_market_proposal_context(market_id)

        probability_snapshot = None
        probability_drift = None
        try:
            probability_snapshot = self.proposal_service.latest_probability_snapshot_for_market(market_id)
            probability_drift = self.proposal_service.compare_probability_snapshots_for_market(market_id)
        except ProposalLifecycleError:
            probability_snapshot = None
            probability_drift = None

        decision_review = self.decision_review_service.latest_persisted_for_market(market_id)

        execution_evaluation = None
        # Execution evaluations are only linked through an explicitly related proposal.
        for proposal in proposal_context.proposals:
            execution_evaluation = self.execution_evaluation_service.latest_persisted_for_proposal(proposal.proposal_id)
            if execution_evaluation is not None:
                break

        return MarketResearchContext(
            market_id=market_id,
            related_proposals=proposal_context.proposals,
            latest_probability_snapshot=probability_snapshot,
            probability_drift=probability_drift,
            latest_decision_review=decision_review,
            latest_execution_evaluation=execution_evaluation,
            latest_outcome_analysis=self._latest_market_analysis("outcomes", market_id),
            latest_learning_analysis=self._latest_market_analysis("learning_summary", market_id),
        )

    def get_market_proposal_context(self, market_id: str) -> MarketProposalContext:
        # Use only explicit market_id linkage for market proposal context.
        proposals = sorted(
            [item for item in self.proposal_service.list_proposals() if item.market_id == market_id],
            key=lambda item: item.updated_at,
            reverse=True,
        )
        latest_proposal = proposals[0] if proposals else None
        latest_decision_review = None
        for proposal in proposals:
            latest_decision_review = self.decision_review_service.latest_persisted_for_proposal(proposal.proposal_id)
            if latest_decision_review is not None:
                break
        return MarketProposalContext(
            market_id=market_id,
            proposals=proposals[:5],
            latest_proposal=latest_proposal,
            latest_decision_review=latest_decision_review,
        )

    def _latest_market_analysis(self, scope: str, market_id: str) -> MarketAnalysisReference | None:
        for snapshot in self.outcome_analysis_service.list_recent_snapshots(limit=25):
            # Only use persisted market-grouped snapshots; omit anything heuristic.
            if snapshot.scope != scope or snapshot.group_by != "market":
                continue
            group = next((item for item in snapshot.groups if item.group_value == market_id), None)
            if group is None:
                continue
            return MarketAnalysisReference(
                snapshot_id=snapshot.snapshot_id,
                scope=snapshot.scope,
                summary=snapshot.summary,
                group=group,
                created_at=snapshot.created_at,
            )
        return None
