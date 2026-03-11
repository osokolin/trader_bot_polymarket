from __future__ import annotations

from datetime import timedelta

from bot.domain.enums import IntentStatus, ProposalStatus
from bot.domain.models import AnalyticsSummary
from bot.services.execution_pipeline import ExecutionPipelineService
from bot.services.proposal_lifecycle import ProposalLifecycleService
from bot.utils.time import utc_now


class AnalyticsService:
    def __init__(
        self,
        proposal_service: ProposalLifecycleService,
        execution_service: ExecutionPipelineService,
    ) -> None:
        self.proposal_service = proposal_service
        self.execution_service = execution_service

    def summarize(self, scope: str, since_hours: int | None = None) -> AnalyticsSummary:
        proposals = self.proposal_service.list_proposals()
        intents = self.execution_service.list_all_intents()
        executions = self.execution_service.list_all_executions()
        if since_hours is not None:
            cutoff = utc_now() - timedelta(hours=since_hours)
            proposals = [item for item in proposals if item.updated_at >= cutoff]
            intents = [item for item in intents if item.updated_at >= cutoff]
            executions = [item for item in executions if item.created_at >= cutoff]
        slippages = [item.slippage_bps for item in executions if item.slippage_bps is not None]
        return AnalyticsSummary(
            scope=scope,
            since_hours=since_hours,
            active_proposal_count=sum(
                1
                for item in proposals
                if item.status in {ProposalStatus.PENDING_MANUAL_CONFIRMATION, ProposalStatus.APPROVED}
            ),
            approved_proposal_count=sum(1 for item in proposals if item.status == ProposalStatus.APPROVED),
            active_intent_count=sum(1 for item in intents if item.status in IntentStatus.active_states()),
            terminal_intent_count=sum(1 for item in intents if item.status in IntentStatus.terminal_states()),
            simulated_execution_count=len(executions),
            total_simulated_filled_size_usd=round(sum(item.filled_size_usd for item in executions), 2),
            average_simulated_slippage_bps=None if not slippages else round(sum(slippages) / len(slippages), 2),
        )
