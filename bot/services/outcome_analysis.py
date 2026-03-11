from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from bot.domain.models import OutcomeAnalysisGroup, OutcomeAnalysisSnapshot
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.storage.repositories import (
    DecisionReviewRepository,
    ExecutionEvaluationRepository,
    OutcomeAnalysisRepository,
)
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class OutcomeAnalysisService:
    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        decision_review_repository: DecisionReviewRepository,
        execution_evaluation_repository: ExecutionEvaluationRepository,
        repository: OutcomeAnalysisRepository,
    ) -> None:
        self.proposal_service = proposal_service
        self.decision_review_repository = decision_review_repository
        self.execution_evaluation_repository = execution_evaluation_repository
        self.repository = repository

    def summarize_outcomes(self, group_by: str, since_hours: int | None = None) -> OutcomeAnalysisSnapshot:
        return self._build_snapshot("outcomes", group_by, since_hours)

    def summarize_learning(self, group_by: str, since_hours: int | None = None) -> OutcomeAnalysisSnapshot:
        return self._build_snapshot("learning_summary", group_by, since_hours)

    def latest_snapshot(self, scope: str, group_by: str) -> OutcomeAnalysisSnapshot | None:
        return self.repository.latest(scope, group_by)

    def list_recent_snapshots(self, limit: int = 5) -> list[OutcomeAnalysisSnapshot]:
        return self.repository.list_all()[:limit]

    def _build_snapshot(self, scope: str, group_by: str, since_hours: int | None) -> OutcomeAnalysisSnapshot:
        proposals = {item.proposal_id: item for item in self.proposal_service.list_proposals()}
        reviews = self.decision_review_repository.list_all()
        evaluations = self.execution_evaluation_repository.list_all()
        if since_hours is not None:
            cutoff = utc_now() - timedelta(hours=since_hours)
            reviews = [item for item in reviews if item.created_at >= cutoff]
            evaluations = [item for item in evaluations if item.created_at >= cutoff]
        buckets: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "review_count": 0,
                "evaluation_count": 0,
                "fair_deltas": [],
                "confidence_deltas": [],
                "confidence_held_count": 0,
                "confidence_degraded_count": 0,
                "probability_in_favor_count": 0,
                "probability_against_count": 0,
                "execution_favorable_count": 0,
                "execution_unfavorable_count": 0,
                "verdict_counts": Counter(),
            }
        )
        for review in reviews:
            proposal = None if review.proposal_id is None else proposals.get(review.proposal_id)
            for key in self._group_keys(group_by, review, proposal):
                bucket = buckets[key]
                payload = review.payload
                drift = payload.get("probability_drift", {})
                outcomes = payload.get("outcomes", {})
                bucket["review_count"] += 1
                fair_delta = drift.get("fair_probability_delta")
                conf_delta = drift.get("confidence_delta")
                if fair_delta is not None:
                    bucket["fair_deltas"].append(fair_delta)
                if conf_delta is not None:
                    bucket["confidence_deltas"].append(conf_delta)
                if outcomes.get("confidence") == "confidence_held":
                    bucket["confidence_held_count"] += 1
                if outcomes.get("confidence") == "confidence_degraded":
                    bucket["confidence_degraded_count"] += 1
                if outcomes.get("probability") == "probability_moved_in_favor":
                    bucket["probability_in_favor_count"] += 1
                if outcomes.get("probability") == "probability_moved_against":
                    bucket["probability_against_count"] += 1
                if outcomes.get("execution") == "execution_favorable":
                    bucket["execution_favorable_count"] += 1
                if outcomes.get("execution") == "execution_unfavorable":
                    bucket["execution_unfavorable_count"] += 1
        for evaluation in evaluations:
            proposal = None if evaluation.proposal_id is None else proposals.get(evaluation.proposal_id)
            for key in self._group_keys(group_by, evaluation, proposal):
                bucket = buckets[key]
                bucket["evaluation_count"] += 1
                bucket["verdict_counts"][evaluation.verdict] += 1
        groups = [
            OutcomeAnalysisGroup(
                group_by=group_by,
                group_value=key,
                review_count=value["review_count"],
                evaluation_count=value["evaluation_count"],
                average_fair_probability_delta=self._average(value["fair_deltas"]),
                average_confidence_delta=self._average(value["confidence_deltas"]),
                confidence_held_count=value["confidence_held_count"],
                confidence_degraded_count=value["confidence_degraded_count"],
                probability_in_favor_count=value["probability_in_favor_count"],
                probability_against_count=value["probability_against_count"],
                execution_favorable_count=value["execution_favorable_count"],
                execution_unfavorable_count=value["execution_unfavorable_count"],
                verdict_counts=dict(sorted(value["verdict_counts"].items())),
            )
            for key, value in sorted(buckets.items())
        ]
        summary = self._summary(scope, group_by, groups)
        snapshot = OutcomeAnalysisSnapshot(
            snapshot_id=new_id("oasnap"),
            scope=scope,
            group_by=group_by,
            since_hours=since_hours,
            groups=groups,
            summary=summary,
            created_at=utc_now(),
        )
        self.repository.save(snapshot)
        return snapshot

    def _group_keys(self, group_by: str, item, proposal) -> list[str]:
        if group_by == "market":
            market_id = getattr(item, "market_id", None)
            if market_id is None and proposal is not None:
                market_id = proposal.market_id
            return [market_id or "unknown_market"]
        if group_by == "category":
            return ["unknown_category" if proposal is None else proposal.market_category]
        if group_by == "source_type":
            if proposal is None:
                return ["unknown_source_type"]
            return [source_type.value for source_type in proposal.source_types] or ["unknown_source_type"]
        if group_by == "confidence_band":
            if proposal is None:
                return ["unknown_confidence_band"]
            confidence = proposal.confidence
            if confidence < 0.75:
                return ["low"]
            if confidence < 0.85:
                return ["medium"]
            return ["high"]
        if group_by == "verdict_type":
            verdict = getattr(item, "verdict", None)
            return [verdict or "no_verdict"]
        raise ValueError(f"Unsupported group_by: {group_by}")

    def _average(self, values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    def _summary(self, scope: str, group_by: str, groups: list[OutcomeAnalysisGroup]) -> str:
        if not groups:
            return f"{scope} produced no groups for {group_by}"
        strongest = max(groups, key=lambda item: item.review_count + item.evaluation_count)
        return (
            f"{scope} grouped by {group_by}: top_group={strongest.group_value} "
            f"signals={strongest.review_count + strongest.evaluation_count}"
        )
