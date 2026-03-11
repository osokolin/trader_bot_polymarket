from __future__ import annotations

from bot.domain.enums import IntentStatus
from bot.domain.models import ExecutionEvaluation, ExecutionEvaluationSnapshot
from bot.services.execution_pipeline import ExecutionBoundaryError, ExecutionPipelineService
from bot.services.proposal_lifecycle import ProposalLifecycleError, ProposalLifecycleService
from bot.storage.repositories import ExecutionEvaluationRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class ExecutionEvaluationError(ValueError):
    pass


class ExecutionEvaluationService:
    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        execution_service: ExecutionPipelineService,
        repository: ExecutionEvaluationRepository,
    ) -> None:
        self.proposal_service = proposal_service
        self.execution_service = execution_service
        self.repository = repository

    def evaluate_intent(self, intent_id: str) -> ExecutionEvaluation:
        intent = self.execution_service.latest_intent_state(intent_id)
        execution = self.execution_service.latest_simulated_execution(intent_id)
        if execution is None:
            raise ExecutionEvaluationError(f"No simulated execution for intent: {intent_id}")
        timeline = self.execution_service.list_execution_timeline(intent_id)
        proposal = self.proposal_service.latest_proposal_state(intent.proposal_id)
        return self._persist_evaluation(
            proposal_id=proposal.proposal_id,
            intent_id=intent.intent_id,
            execution=execution,
            intended_price=intent.limit_price,
            expected_size_usd=intent.size_usd,
            timeline=timeline,
        )

    def evaluate_proposal(self, proposal_id: str) -> ExecutionEvaluation:
        proposal = self.proposal_service.latest_proposal_state(proposal_id)
        intent = self.execution_service.latest_intent_for_proposal(proposal_id)
        if intent is None:
            raise ExecutionEvaluationError(f"No order intent for proposal: {proposal_id}")
        execution = self.execution_service.latest_simulated_execution(intent.intent_id)
        if execution is None:
            raise ExecutionEvaluationError(f"No simulated execution for proposal: {proposal_id}")
        timeline = self.execution_service.list_execution_timeline(intent.intent_id)
        return self._persist_evaluation(
            proposal_id=proposal.proposal_id,
            intent_id=intent.intent_id,
            execution=execution,
            intended_price=intent.limit_price,
            expected_size_usd=intent.size_usd,
            timeline=timeline,
        )

    def latest_persisted_for_intent(self, intent_id: str) -> ExecutionEvaluationSnapshot | None:
        return self.repository.latest_for_intent(intent_id)

    def latest_persisted_for_proposal(self, proposal_id: str) -> ExecutionEvaluationSnapshot | None:
        return self.repository.latest_for_proposal(proposal_id)

    def list_recent(self, limit: int = 5) -> list[ExecutionEvaluationSnapshot]:
        return self.repository.list_all()[:limit]

    def _persist_evaluation(
        self,
        proposal_id: str | None,
        intent_id: str,
        execution,
        intended_price: float,
        expected_size_usd: float,
        timeline,
    ) -> ExecutionEvaluation:
        created_at = utc_now()
        realized_price = execution.simulated_price
        price_delta = None if realized_price is None else round(realized_price - intended_price, 4)
        size_fill_ratio = 0.0 if expected_size_usd <= 0 else round(execution.filled_size_usd / expected_size_usd, 4)
        expected_latency_ms = self._expected_latency_ms(expected_size_usd)
        realized_latency_ms = execution.latency_ms
        latency_delta_ms = None if realized_latency_ms is None else realized_latency_ms - expected_latency_ms
        intended_completion = "full_fill_expected"
        actual_completion_reason = execution.completion_reason or execution.status.value
        verdict = self._verdict(execution.status, size_fill_ratio, price_delta, latency_delta_ms)
        summary = (
            f"verdict={verdict}, intended_price={intended_price:.4f}, "
            f"realized_price={'-' if realized_price is None else f'{realized_price:.4f}'}, "
            f"filled={execution.filled_size_usd:.2f}/{expected_size_usd:.2f}, "
            f"latency_ms={'-' if realized_latency_ms is None else realized_latency_ms}, "
            f"completion={actual_completion_reason}"
        )
        evaluation = ExecutionEvaluation(
            evaluation_id=new_id("eeval"),
            proposal_id=proposal_id,
            intent_id=intent_id,
            execution_id=execution.execution_id,
            verdict=verdict,
            intended_price=intended_price,
            realized_price=realized_price,
            expected_size_usd=expected_size_usd,
            filled_size_usd=execution.filled_size_usd,
            expected_latency_ms=expected_latency_ms,
            realized_latency_ms=realized_latency_ms,
            intended_completion=intended_completion,
            actual_completion_reason=actual_completion_reason,
            size_fill_ratio=size_fill_ratio,
            price_delta=price_delta,
            latency_delta_ms=latency_delta_ms,
            timeline_event_count=len(timeline),
            summary=summary,
            created_at=created_at,
        )
        self.repository.save(
            ExecutionEvaluationSnapshot(
                evaluation_id=evaluation.evaluation_id,
                proposal_id=proposal_id,
                intent_id=intent_id,
                execution_id=execution.execution_id,
                verdict=verdict,
                summary=summary,
                payload={
                    "intended_price": intended_price,
                    "realized_price": realized_price,
                    "price_delta": price_delta,
                    "expected_size_usd": expected_size_usd,
                    "filled_size_usd": execution.filled_size_usd,
                    "size_fill_ratio": size_fill_ratio,
                    "expected_latency_ms": expected_latency_ms,
                    "realized_latency_ms": realized_latency_ms,
                    "latency_delta_ms": latency_delta_ms,
                    "intended_completion": intended_completion,
                    "actual_completion_reason": actual_completion_reason,
                    "timeline_event_count": len(timeline),
                    "execution_status": execution.status.value,
                },
                created_at=created_at,
            )
        )
        return evaluation

    def _expected_latency_ms(self, expected_size_usd: float) -> int:
        if expected_size_usd <= 50:
            return 250
        if expected_size_usd <= 100:
            return 600
        return 900

    def _verdict(
        self,
        status: IntentStatus,
        size_fill_ratio: float,
        price_delta: float | None,
        latency_delta_ms: int | None,
    ) -> str:
        if status == IntentStatus.SIMULATED_EXPIRED:
            return "expired"
        if status == IntentStatus.SIMULATED_CANCELLED:
            return "cancelled"
        if status == IntentStatus.SIMULATED_PARTIALLY_FILLED or size_fill_ratio < 1.0:
            return "partially_filled"
        if price_delta is not None and price_delta < -0.002 and (latency_delta_ms is None or latency_delta_ms <= 0):
            return "better_than_expected"
        if price_delta is not None and price_delta > 0.005:
            return "worse_than_expected"
        if latency_delta_ms is not None and latency_delta_ms > 250:
            return "worse_than_expected"
        return "within_expected_range"
