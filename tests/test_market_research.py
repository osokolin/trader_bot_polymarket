from __future__ import annotations

from datetime import timedelta
import unittest

from bot.domain.decisions import PolicyDecision
from bot.domain.enums import ProposalStatus, SourceType, TradeAction
from bot.domain.models import (
    DecisionReviewSnapshot,
    ExecutionEvaluationSnapshot,
    OutcomeAnalysisGroup,
    OutcomeAnalysisSnapshot,
    ProbabilityDrift,
    ProbabilityEstimate,
    ProbabilitySnapshot,
    ResearchSummary,
    TradeProposal,
)
from bot.services.market_research import MarketResearchService
from bot.services.proposal_lifecycle import ProposalLifecycleError
from bot.utils.time import utc_now


class _FakeProposalService:
    def __init__(self, proposal: TradeProposal, snapshot: ProbabilitySnapshot, drift: ProbabilityDrift) -> None:
        self.proposal = proposal
        self.snapshot = snapshot
        self.drift = drift

    def list_proposals(self) -> list[TradeProposal]:
        return [self.proposal]

    def latest_probability_snapshot_for_market(self, market_id: str) -> ProbabilitySnapshot:
        if market_id != self.snapshot.market_id:
            raise ProposalLifecycleError("missing")
        return self.snapshot

    def compare_probability_snapshots_for_market(self, market_id: str) -> ProbabilityDrift:
        if market_id != self.snapshot.market_id:
            raise ProposalLifecycleError("missing")
        return self.drift


class _NoSnapshotProposalService(_FakeProposalService):
    def latest_probability_snapshot_for_market(self, market_id: str) -> ProbabilitySnapshot:
        raise ProposalLifecycleError("missing")

    def compare_probability_snapshots_for_market(self, market_id: str) -> ProbabilityDrift:
        raise ProposalLifecycleError("missing")


class _FakeDecisionReviewService:
    def __init__(self, review: DecisionReviewSnapshot | None) -> None:
        self.review = review

    def latest_persisted_for_market(self, market_id: str) -> DecisionReviewSnapshot | None:
        return self.review if self.review is not None and self.review.market_id == market_id else None

    def latest_persisted_for_proposal(self, proposal_id: str) -> DecisionReviewSnapshot | None:
        return self.review if self.review is not None and self.review.proposal_id == proposal_id else None


class _FakeExecutionEvaluationService:
    def __init__(self, evaluation: ExecutionEvaluationSnapshot | None) -> None:
        self.evaluation = evaluation

    def latest_persisted_for_proposal(self, proposal_id: str) -> ExecutionEvaluationSnapshot | None:
        return self.evaluation if self.evaluation is not None and self.evaluation.proposal_id == proposal_id else None


class _FakeOutcomeAnalysisService:
    def __init__(self, snapshots: list[OutcomeAnalysisSnapshot]) -> None:
        self.snapshots = snapshots

    def list_recent_snapshots(self, limit: int = 5) -> list[OutcomeAnalysisSnapshot]:
        return self.snapshots[:limit]


class MarketResearchServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        now = utc_now()
        self.proposal = TradeProposal(
            proposal_id="proposal_market_ctx",
            market_id="mkt_ctx",
            market_title="Will CPI print below consensus?",
            market_category="macro",
            action=TradeAction.BUY,
            side="yes",
            market_price=0.46,
            fair_probability=0.62,
            edge=0.16,
            confidence=0.88,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
            current_size_usd=25.0,
            current_limit_price=0.47,
            recommended_size_usd=25.0,
            max_allowed_size_usd=50.0,
            suggested_limit_price=0.47,
            thesis=["soft labor data"],
            risks=["revision risk"],
            status=ProposalStatus.APPROVED,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
            policy_decision=PolicyDecision(allowed=True, reasons=[], details={}),
        )
        estimate = ProbabilityEstimate(
            market_id="mkt_ctx",
            fair_probability=0.62,
            confidence=0.88,
            model_agreement=3,
            trusted_source_present=True,
            source_types=[SourceType.OFFICIAL],
            key_factors=["soft labor data"],
            source_count=1,
            confidence_components={"model": 0.88},
            explanation="Official macro data supports the thesis.",
        )
        self.snapshot = ProbabilitySnapshot(
            snapshot_id="psnap_ctx",
            market_id="mkt_ctx",
            proposal_id=self.proposal.proposal_id,
            probability=estimate,
            research_summary=ResearchSummary(
                market_id="mkt_ctx",
                proposal_id=self.proposal.proposal_id,
                summary="Official macro data supports the thesis.",
                key_factors=["soft labor data"],
                thesis_points=["soft labor data"],
                risk_points=["revision risk"],
                source_count=1,
                evidence_summary=["BLS labor report"],
            ),
            current_price=0.46,
            data_age_seconds=30,
            created_at=now - timedelta(minutes=30),
        )
        self.drift = ProbabilityDrift(
            scope="market",
            latest_snapshot=self.snapshot,
            previous_snapshot=None,
            fair_probability_delta=None,
            confidence_delta=None,
            source_count_delta=None,
            confidence_component_deltas={},
            source_type_contribution_deltas={},
            drift_summary="insufficient history",
        )
        self.review = DecisionReviewSnapshot(
            review_id="dreview_ctx",
            scope="market",
            market_id="mkt_ctx",
            proposal_id=self.proposal.proposal_id,
            probability_snapshot_id=self.snapshot.snapshot_id,
            previous_snapshot_id=None,
            intent_id=None,
            execution_id=None,
            confidence_outcome="confidence_held",
            probability_outcome="probability_moved_in_favor",
            execution_outcome="execution_not_simulated",
            summary="confidence held, probability moved in favor",
            payload={},
            created_at=now - timedelta(minutes=20),
        )
        self.evaluation = ExecutionEvaluationSnapshot(
            evaluation_id="eeval_ctx",
            proposal_id=self.proposal.proposal_id,
            intent_id="intent_ctx",
            execution_id="execution_ctx",
            verdict="within_expected_range",
            summary="Execution within expected range",
            payload={},
            created_at=now - timedelta(minutes=10),
        )
        self.outcomes_snapshot = OutcomeAnalysisSnapshot(
            snapshot_id="oasnap_outcomes",
            scope="outcomes",
            group_by="market",
            since_hours=None,
            groups=[
                OutcomeAnalysisGroup(
                    group_by="market",
                    group_value="mkt_ctx",
                    review_count=1,
                    evaluation_count=1,
                    average_fair_probability_delta=0.02,
                    average_confidence_delta=0.01,
                    confidence_held_count=1,
                    confidence_degraded_count=0,
                    probability_in_favor_count=1,
                    probability_against_count=0,
                    execution_favorable_count=0,
                    execution_unfavorable_count=0,
                    verdict_counts={"within_expected_range": 1},
                )
            ],
            summary="outcomes grouped by market",
            created_at=now - timedelta(minutes=5),
        )
        self.learning_snapshot = OutcomeAnalysisSnapshot(
            snapshot_id="oasnap_learning",
            scope="learning_summary",
            group_by="market",
            since_hours=None,
            groups=[
                OutcomeAnalysisGroup(
                    group_by="market",
                    group_value="mkt_ctx",
                    review_count=1,
                    evaluation_count=1,
                    average_fair_probability_delta=0.02,
                    average_confidence_delta=0.01,
                    confidence_held_count=1,
                    confidence_degraded_count=0,
                    probability_in_favor_count=1,
                    probability_against_count=0,
                    execution_favorable_count=0,
                    execution_unfavorable_count=0,
                    verdict_counts={"within_expected_range": 1},
                )
            ],
            summary="learning grouped by market",
            created_at=now - timedelta(minutes=4),
        )

    def test_market_research_context_aggregates_existing_artifacts(self) -> None:
        service = MarketResearchService(
            proposal_service=_FakeProposalService(self.proposal, self.snapshot, self.drift),  # type: ignore[arg-type]
            decision_review_service=_FakeDecisionReviewService(self.review),  # type: ignore[arg-type]
            execution_evaluation_service=_FakeExecutionEvaluationService(self.evaluation),  # type: ignore[arg-type]
            outcome_analysis_service=_FakeOutcomeAnalysisService([self.learning_snapshot, self.outcomes_snapshot]),  # type: ignore[arg-type]
        )

        context = service.get_market_research_context("mkt_ctx")

        self.assertTrue(context.has_artifacts)
        self.assertEqual(context.latest_probability_snapshot.snapshot_id, "psnap_ctx")  # type: ignore[union-attr]
        self.assertEqual(context.latest_decision_review.review_id, "dreview_ctx")  # type: ignore[union-attr]
        self.assertEqual(context.latest_execution_evaluation.evaluation_id, "eeval_ctx")  # type: ignore[union-attr]
        self.assertEqual(context.latest_outcome_analysis.snapshot_id, "oasnap_outcomes")  # type: ignore[union-attr]
        self.assertEqual(context.latest_learning_analysis.snapshot_id, "oasnap_learning")  # type: ignore[union-attr]
        self.assertEqual([item.proposal_id for item in context.related_proposals], ["proposal_market_ctx"])

    def test_market_proposal_context_aggregates_latest_proposal_and_review(self) -> None:
        service = MarketResearchService(
            proposal_service=_FakeProposalService(self.proposal, self.snapshot, self.drift),  # type: ignore[arg-type]
            decision_review_service=_FakeDecisionReviewService(self.review),  # type: ignore[arg-type]
            execution_evaluation_service=_FakeExecutionEvaluationService(self.evaluation),  # type: ignore[arg-type]
            outcome_analysis_service=_FakeOutcomeAnalysisService([self.learning_snapshot, self.outcomes_snapshot]),  # type: ignore[arg-type]
        )

        context = service.get_market_proposal_context("mkt_ctx")

        self.assertEqual(context.proposal_count, 1)
        self.assertEqual(context.latest_proposal.proposal_id, "proposal_market_ctx")  # type: ignore[union-attr]
        self.assertEqual(context.latest_decision_review.review_id, "dreview_ctx")  # type: ignore[union-attr]
        self.assertEqual([item.proposal_id for item in context.proposals], ["proposal_market_ctx"])

    def test_market_research_context_returns_clean_empty_state_when_missing(self) -> None:
        service = MarketResearchService(
            proposal_service=_NoSnapshotProposalService(self.proposal, self.snapshot, self.drift),  # type: ignore[arg-type]
            decision_review_service=_FakeDecisionReviewService(None),  # type: ignore[arg-type]
            execution_evaluation_service=_FakeExecutionEvaluationService(None),  # type: ignore[arg-type]
            outcome_analysis_service=_FakeOutcomeAnalysisService([]),  # type: ignore[arg-type]
        )

        context = service.get_market_research_context("mkt_missing")

        self.assertFalse(context.has_artifacts)
        self.assertIsNone(context.latest_probability_snapshot)
        self.assertIsNone(context.latest_decision_review)
        self.assertIsNone(context.latest_execution_evaluation)
        self.assertIsNone(context.latest_outcome_analysis)
        self.assertEqual(context.related_proposals, [])

    def test_market_proposal_context_returns_empty_state_when_missing(self) -> None:
        service = MarketResearchService(
            proposal_service=_NoSnapshotProposalService(self.proposal, self.snapshot, self.drift),  # type: ignore[arg-type]
            decision_review_service=_FakeDecisionReviewService(None),  # type: ignore[arg-type]
            execution_evaluation_service=_FakeExecutionEvaluationService(None),  # type: ignore[arg-type]
            outcome_analysis_service=_FakeOutcomeAnalysisService([]),  # type: ignore[arg-type]
        )

        context = service.get_market_proposal_context("mkt_missing")

        self.assertEqual(context.proposal_count, 0)
        self.assertIsNone(context.latest_proposal)
        self.assertIsNone(context.latest_decision_review)


if __name__ == "__main__":
    unittest.main()
