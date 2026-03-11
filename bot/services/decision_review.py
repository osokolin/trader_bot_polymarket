from __future__ import annotations

from bot.domain.models import (
    DecisionReview,
    DecisionReviewSnapshot,
    OrderIntent,
    ProbabilityDrift,
    SimulatedExecution,
)
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.repositories import DecisionReviewRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class DecisionReviewError(ValueError):
    pass


class DecisionReviewService:
    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        execution_service: ExecutionPipelineService,
        repository: DecisionReviewRepository,
    ) -> None:
        self.proposal_service = proposal_service
        self.execution_service = execution_service
        self.repository = repository

    def create_for_proposal(self, proposal_id: str) -> DecisionReview:
        proposal = self.proposal_service.latest_proposal_state(proposal_id)
        snapshot = self.proposal_service.latest_probability_snapshot_for_proposal(proposal_id)
        drift = self.proposal_service.compare_probability_snapshots_for_proposal(proposal_id)
        latest_intent = self.execution_service.latest_intent_for_proposal(proposal_id)
        latest_execution = None if latest_intent is None else self.execution_service.latest_simulated_execution(latest_intent.intent_id)
        return self._persist_review(
            scope="proposal",
            market_id=proposal.market_id,
            proposal=proposal,
            drift=drift,
            latest_intent=latest_intent,
            latest_execution=latest_execution,
        )

    def create_for_market(self, market_id: str) -> DecisionReview:
        snapshot = self.proposal_service.latest_probability_snapshot_for_market(market_id)
        drift = self.proposal_service.compare_probability_snapshots_for_market(market_id)
        proposal = None
        if snapshot.proposal_id is not None:
            proposal = self.proposal_service.latest_proposal_state(snapshot.proposal_id)
        latest_intent = None if proposal is None else self.execution_service.latest_intent_for_proposal(proposal.proposal_id)
        latest_execution = None if latest_intent is None else self.execution_service.latest_simulated_execution(latest_intent.intent_id)
        return self._persist_review(
            scope="market",
            market_id=market_id,
            proposal=proposal,
            drift=drift,
            latest_intent=latest_intent,
            latest_execution=latest_execution,
        )

    def latest_persisted_for_proposal(self, proposal_id: str) -> DecisionReviewSnapshot | None:
        return self.repository.latest_for_proposal(proposal_id)

    def latest_persisted_for_market(self, market_id: str) -> DecisionReviewSnapshot | None:
        return self.repository.latest_for_market(market_id)

    def list_recent(self, limit: int = 5) -> list[DecisionReviewSnapshot]:
        return self.repository.list_all()[:limit]

    def _persist_review(
        self,
        scope: str,
        market_id: str,
        proposal,
        drift: ProbabilityDrift,
        latest_intent: OrderIntent | None,
        latest_execution: SimulatedExecution | None,
    ) -> DecisionReview:
        created_at = utc_now()
        confidence_outcome = self._confidence_outcome(drift)
        probability_outcome = self._probability_outcome(proposal.side if proposal is not None else None, drift)
        execution_outcome = self._execution_outcome(proposal.side if proposal is not None else None, latest_execution)
        summary = ", ".join(
            [
                f"confidence={confidence_outcome}",
                f"probability={probability_outcome}",
                f"execution={execution_outcome}",
            ]
        )
        review = DecisionReview(
            review_id=new_id("dreview"),
            scope=scope,
            market_id=market_id,
            proposal=proposal,
            probability_snapshot=drift.latest_snapshot,
            probability_drift=drift,
            latest_intent=latest_intent,
            latest_execution=latest_execution,
            confidence_outcome=confidence_outcome,
            probability_outcome=probability_outcome,
            execution_outcome=execution_outcome,
            summary=summary,
            created_at=created_at,
        )
        self.repository.save(
            DecisionReviewSnapshot(
                review_id=review.review_id,
                scope=scope,
                market_id=market_id,
                proposal_id=None if proposal is None else proposal.proposal_id,
                probability_snapshot_id=drift.latest_snapshot.snapshot_id,
                previous_snapshot_id=None if drift.previous_snapshot is None else drift.previous_snapshot.snapshot_id,
                intent_id=None if latest_intent is None else latest_intent.intent_id,
                execution_id=None if latest_execution is None else latest_execution.execution_id,
                confidence_outcome=confidence_outcome,
                probability_outcome=probability_outcome,
                execution_outcome=execution_outcome,
                summary=summary,
                payload=self._payload(review),
                created_at=created_at,
            )
        )
        return review

    def _payload(self, review: DecisionReview) -> dict[str, object]:
        proposal = review.proposal
        drift = review.probability_drift
        intent = review.latest_intent
        execution = review.latest_execution
        snapshot = review.probability_snapshot
        if drift is None or snapshot is None:
            raise DecisionReviewError("Decision review requires a latest probability snapshot and drift context")
        return {
            "proposal": None
            if proposal is None
            else {
                "proposal_id": proposal.proposal_id,
                "status": proposal.status.value,
                "side": proposal.side,
                "market_price": proposal.market_price,
                "fair_probability": proposal.fair_probability,
                "confidence": proposal.confidence,
            },
            "probability_snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "fair_probability": snapshot.probability.fair_probability,
                "confidence": snapshot.probability.confidence,
                "source_count": snapshot.probability.source_count,
                "key_factors": snapshot.probability.key_factors,
                "confidence_components": snapshot.probability.confidence_components,
                "created_at": snapshot.created_at.isoformat(),
            },
            "probability_drift": {
                "previous_snapshot_id": None if drift.previous_snapshot is None else drift.previous_snapshot.snapshot_id,
                "fair_probability_delta": drift.fair_probability_delta,
                "confidence_delta": drift.confidence_delta,
                "source_count_delta": drift.source_count_delta,
                "confidence_component_deltas": drift.confidence_component_deltas,
                "added_key_factors": drift.added_key_factors,
                "removed_key_factors": drift.removed_key_factors,
                "drift_summary": drift.drift_summary,
            },
            "intent": None
            if intent is None
            else {
                "intent_id": intent.intent_id,
                "status": intent.status.value,
                "size_usd": intent.size_usd,
                "limit_price": intent.limit_price,
                "updated_at": intent.updated_at.isoformat(),
            },
            "execution": None
            if execution is None
            else {
                "execution_id": execution.execution_id,
                "status": execution.status.value,
                "accepted": execution.accepted,
                "reference_price": execution.reference_price,
                "simulated_price": execution.simulated_price,
                "slippage_bps": execution.slippage_bps,
                "filled_size_usd": execution.filled_size_usd,
                "fill_timestamp": None if execution.fill_timestamp is None else execution.fill_timestamp.isoformat(),
            },
            "outcomes": {
                "confidence": review.confidence_outcome,
                "probability": review.probability_outcome,
                "execution": review.execution_outcome,
            },
            "summary": review.summary,
        }

    def _confidence_outcome(self, drift: ProbabilityDrift) -> str:
        if drift.previous_snapshot is None or drift.confidence_delta is None:
            return "confidence_insufficient_history"
        if drift.confidence_delta < 0:
            return "confidence_degraded"
        return "confidence_held"

    def _probability_outcome(self, side: str | None, drift: ProbabilityDrift) -> str:
        if side is None or drift.previous_snapshot is None or drift.fair_probability_delta is None:
            return "probability_insufficient_history"
        moved_in_favor = drift.fair_probability_delta >= 0 if side == "yes" else drift.fair_probability_delta <= 0
        return "probability_moved_in_favor" if moved_in_favor else "probability_moved_against"

    def _execution_outcome(self, side: str | None, execution: SimulatedExecution | None) -> str:
        if side is None or execution is None or execution.simulated_price is None:
            return "execution_not_simulated"
        if not execution.accepted:
            return "execution_unfavorable"
        favorable = execution.simulated_price <= execution.reference_price if side == "yes" else execution.simulated_price >= execution.reference_price
        return "execution_favorable" if favorable else "execution_unfavorable"
