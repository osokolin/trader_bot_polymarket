from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

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
from bot.utils.time import utc_now


@dataclass(slots=True)
class MarketAnalysisReference:
    snapshot_id: str
    scope: str
    summary: str
    group: OutcomeAnalysisGroup
    created_at: datetime


@dataclass(slots=True)
class MarketCardSignals:
    market_id: str
    has_research: bool
    proposal_count: int
    has_review: bool
    has_analysis: bool
    is_fresh: bool
    latest_artifact_at: datetime | None
    fresh_label: str | None


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
    FRESHNESS_WINDOW = timedelta(hours=24)

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

    def get_market_card_signals(self, market_id: str) -> MarketCardSignals:
        proposal_context = self.get_market_proposal_context(market_id)
        research_context = self.get_market_research_context(market_id)

        timestamps = [
            item
            for item in (
                research_context.latest_probability_snapshot.created_at if research_context.latest_probability_snapshot else None,
                proposal_context.latest_proposal.updated_at if proposal_context.latest_proposal else None,
                research_context.latest_decision_review.created_at if research_context.latest_decision_review else None,
                research_context.latest_execution_evaluation.created_at if research_context.latest_execution_evaluation else None,
                research_context.latest_outcome_analysis.created_at if research_context.latest_outcome_analysis else None,
                research_context.latest_learning_analysis.created_at if research_context.latest_learning_analysis else None,
            )
            if item is not None
        ]
        latest_artifact_at = max(timestamps) if timestamps else None
        is_fresh = latest_artifact_at is not None and latest_artifact_at >= utc_now() - self.FRESHNESS_WINDOW

        return MarketCardSignals(
            market_id=market_id,
            has_research=research_context.latest_probability_snapshot is not None,
            proposal_count=proposal_context.proposal_count,
            has_review=research_context.latest_decision_review is not None,
            has_analysis=any(
                item is not None
                for item in (
                    research_context.latest_execution_evaluation,
                    research_context.latest_outcome_analysis,
                    research_context.latest_learning_analysis,
                )
            ),
            is_fresh=is_fresh,
            latest_artifact_at=latest_artifact_at,
            fresh_label=self._fresh_label(latest_artifact_at) if is_fresh and latest_artifact_at is not None else None,
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

    def _fresh_label(self, latest_artifact_at: datetime) -> str:
        age = utc_now() - latest_artifact_at
        total_hours = int(age.total_seconds() // 3600)
        if total_hours < 1:
            return "Fresh <1h"
        if total_hours < 24:
            return f"Fresh {total_hours}h"
        total_days = max(1, total_hours // 24)
        return f"Fresh {total_days}d"
