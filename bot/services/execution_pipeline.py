from __future__ import annotations

from dataclasses import replace

from bot.adapters.polymarket.models import OrderRequest, SubmissionOutcome
from bot.adapters.polymarket.trading import ExecutionAdapter, PaperExecutionAdapter
from bot.config.models import Settings
from bot.domain.enums import BotMode, IntentStatus, ProposalStatus
from bot.domain.models import OrderIntent, SimulatedExecution, SimulatedFillEvent, SimulationSummary, TradeProposal
from bot.services.audit_log import AuditLogService
from bot.services.execution_guard import ManualExecutionGuard
from bot.services.operator_notifications import OperatorNotificationsService
from bot.storage.repositories import OrderIntentRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class ExecutionBoundaryError(ValueError):
    pass


class ExecutionPipelineService:
    def __init__(
        self,
        settings: Settings,
        execution_adapter: ExecutionAdapter,
        order_intent_repository: OrderIntentRepository,
        audit_log: AuditLogService,
        paper_execution_adapter: ExecutionAdapter | None = None,
        notifications_service: OperatorNotificationsService | None = None,
    ) -> None:
        self.settings = settings
        self.execution_adapter = execution_adapter
        self.paper_execution_adapter = paper_execution_adapter or PaperExecutionAdapter()
        self.order_intent_repository = order_intent_repository
        self.audit_log = audit_log
        self.guard = ManualExecutionGuard(execution_adapter)
        self.notifications_service = notifications_service

    def create_order_intent(
        self,
        proposal: TradeProposal,
        reason: str = "manual_submission",
        supersede_existing: bool = False,
    ) -> OrderIntent:
        if proposal.status != ProposalStatus.APPROVED:
            raise ExecutionBoundaryError("Only approved proposals can become order intents")
        now = utc_now()
        if proposal.expires_at <= now:
            raise ExecutionBoundaryError("Approved proposal is stale and cannot become an order intent")
        existing_active = self.order_intent_repository.list_active_for_proposal(proposal.proposal_id)
        if existing_active and not supersede_existing:
            raise ExecutionBoundaryError("An active order intent already exists for this proposal")
        intent = OrderIntent(
            intent_id=new_id("intent"),
            proposal_id=proposal.proposal_id,
            market_id=proposal.market_id,
            side=proposal.side,
            size_usd=proposal.current_size_usd,
            limit_price=proposal.current_limit_price,
            status=IntentStatus.CREATED,
            created_at=now,
            updated_at=now,
            reason=reason,
        )
        if existing_active:
            for active_intent in existing_active:
                superseded = replace(
                    active_intent,
                    status=IntentStatus.SUPERSEDED,
                    superseded_by_intent_id=intent.intent_id,
                    updated_at=now,
                )
                self.order_intent_repository.save(superseded)
                if self.notifications_service is not None:
                    self.notifications_service.create_superseded_intent_alert(
                        active_intent.intent_id,
                        active_intent.proposal_id,
                        active_intent.market_id,
                        intent.intent_id,
                    )
        self.order_intent_repository.save(intent)
        self._record_review(intent.intent_id, "create", "system", None, {"proposal_id": proposal.proposal_id}, now)
        self.audit_log.log(
            "order_intent_created",
            intent.intent_id,
            "Order intent created from approved proposal",
            {"proposal_id": proposal.proposal_id, "market_id": proposal.market_id},
            created_at=now,
        )
        return intent

    def prepare_submission(self, intent_id: str) -> SubmissionOutcome:
        intent = self._get_intent(intent_id)
        if intent.status != IntentStatus.CREATED:
            raise ExecutionBoundaryError("Only intents in created status can be prepared")
        self.guard.ensure_manual_only()
        result = self.execution_adapter.prepare_order(
            OrderRequest(
                market_id=intent.market_id,
                side=intent.side,
                size_usd=intent.size_usd,
                limit_price=intent.limit_price,
            )
        )
        now = utc_now()
        status = IntentStatus.PREPARED if result.accepted else IntentStatus.BLOCKED
        updated_intent = replace(intent, status=status, updated_at=now)
        self.order_intent_repository.save(updated_intent)
        self._record_review(updated_intent.intent_id, "prepare", "system", None, {"status": status.value}, now)
        outcome = SubmissionOutcome(stage=status.value, accepted=result.accepted, message=result.message)
        self.audit_log.log(
            "order_submission_prepared",
            updated_intent.intent_id,
            "Order intent prepared for manual submission",
            {"accepted": result.accepted, "message": result.message, "status": status.value},
            created_at=now,
        )
        return outcome

    def submit_intent(self, intent_id: str) -> SubmissionOutcome:
        intent = self._get_intent(intent_id)
        if intent.status != IntentStatus.PREPARED:
            raise ExecutionBoundaryError("Only intents in prepared status can be submitted")
        self.guard.ensure_manual_only()
        now = utc_now()
        if self.settings.mode == BotMode.SEMI_AUTO:
            disabled_intent = replace(intent, status=IntentStatus.SUBMISSION_DISABLED, updated_at=now)
            self.order_intent_repository.save(disabled_intent)
            self._record_review(disabled_intent.intent_id, "submit_blocked", "system", None, {"status": disabled_intent.status.value}, now)
            self.audit_log.log(
                "order_submission_disabled",
                disabled_intent.intent_id,
                "Order submission blocked by semi_auto execution boundary",
                {"status": disabled_intent.status.value},
                created_at=now,
            )
            raise ExecutionBoundaryError("semi_auto mode forbids autonomous order submission")
        result = self.execution_adapter.submit_order(
            OrderRequest(
                market_id=intent.market_id,
                side=intent.side,
                size_usd=intent.size_usd,
                limit_price=intent.limit_price,
            )
        )
        status = IntentStatus.SUBMISSION_ACCEPTED if result.accepted else IntentStatus.SUBMISSION_REJECTED
        updated_intent = replace(intent, status=status, updated_at=now)
        self.order_intent_repository.save(updated_intent)
        self._record_review(updated_intent.intent_id, "submit", "system", None, {"status": status.value}, now)
        outcome = SubmissionOutcome(stage=status.value, accepted=result.accepted, message=result.message)
        self.audit_log.log(
            "order_submission_attempted",
            updated_intent.intent_id,
            "Order submission attempted",
            {"accepted": result.accepted, "message": result.message, "status": status.value},
            created_at=now,
        )
        return outcome

    def simulate_intent(
        self,
        intent_id: str,
        actor: str,
        best_bid: float | None = None,
        best_ask: float | None = None,
        ttl_ms: int | None = None,
        cancel_after_ms: int | None = None,
        base_latency_ms: int | None = None,
    ) -> SubmissionOutcome:
        intent = self._get_intent(intent_id)
        if intent.status in self._terminal_simulation_states():
            raise ExecutionBoundaryError("Terminal simulated intents cannot be simulated again")
        if intent.status != IntentStatus.PREPARED:
            raise ExecutionBoundaryError("Only intents in prepared status can be simulated")
        now = utc_now()
        result = self.paper_execution_adapter.simulate_order(
            OrderRequest(
                market_id=intent.market_id,
                side=intent.side,
                size_usd=intent.size_usd,
                limit_price=intent.limit_price,
                best_bid=best_bid,
                best_ask=best_ask,
                ttl_ms=ttl_ms,
                cancel_after_ms=cancel_after_ms,
                base_latency_ms=base_latency_ms,
            )
        )
        status = IntentStatus(result.stage)
        updated_intent = replace(intent, status=status, updated_at=now)
        self.order_intent_repository.save(updated_intent)
        execution = SimulatedExecution(
            execution_id=new_id("simexec"),
            intent_id=intent.intent_id,
            status=status,
            accepted=result.accepted,
            order_id=result.order_id,
            reference_price=result.reference_price,
            best_bid=result.best_bid,
            best_ask=result.best_ask,
            simulated_price=result.simulated_price,
            slippage_bps=result.slippage_bps,
            filled_size_usd=result.filled_size_usd,
            fill_timestamp=result.fill_timestamp,
            latency_ms=result.latency_ms,
            completion_reason=result.completion_reason,
            message=result.message,
            created_at=now,
        )
        self.order_intent_repository.save_execution(execution)
        fill_events = [
            SimulatedFillEvent(
                event_id=new_id("sfill"),
                execution_id=execution.execution_id,
                intent_id=intent.intent_id,
                event_type=fragment.event_type,
                fragment_index=fragment.fragment_index,
                price=fragment.price,
                size_usd=fragment.size_usd,
                remaining_size_usd=fragment.remaining_size_usd,
                latency_ms=fragment.latency_ms,
                event_timestamp=fragment.event_timestamp,
                message=fragment.message,
            )
            for fragment in result.fill_fragments
        ]
        if fill_events:
            self.order_intent_repository.save_fill_events(fill_events)
        if self.notifications_service is not None:
            self.notifications_service.create_simulated_execution_alert(
                intent.intent_id,
                intent.proposal_id,
                intent.market_id,
                execution.execution_id,
                execution.status.value,
            )
        payload = self._simulation_payload(execution)
        self._record_review(updated_intent.intent_id, "simulate_execution", actor, None, payload, now)
        self.audit_log.log(
            "order_execution_simulated",
            updated_intent.intent_id,
            "Paper execution simulated for order intent",
            payload | {"actor": actor},
            created_at=now,
        )
        return SubmissionOutcome(
            stage=status.value,
            accepted=result.accepted,
            message=result.message,
            order_id=result.order_id,
            reference_price=result.reference_price,
            best_bid=result.best_bid,
            best_ask=result.best_ask,
            simulated_price=result.simulated_price,
            slippage_bps=result.slippage_bps,
            filled_size_usd=result.filled_size_usd,
            fill_timestamp=result.fill_timestamp,
            latency_ms=result.latency_ms,
            completion_reason=result.completion_reason,
        )

    def _get_intent(self, intent_id: str) -> OrderIntent:
        intent = self.order_intent_repository.get(intent_id)
        if intent is None:
            raise ExecutionBoundaryError(f"Unknown order intent: {intent_id}")
        return intent

    def latest_active_intent(self, proposal_id: str) -> OrderIntent | None:
        return self.order_intent_repository.latest_active_for_proposal(proposal_id)

    def latest_intent_for_proposal(self, proposal_id: str) -> OrderIntent | None:
        return self.order_intent_repository.latest_for_proposal(proposal_id)

    def latest_intent_state(self, intent_id: str) -> OrderIntent:
        intent = self.order_intent_repository.latest_state(intent_id)
        if intent is None:
            raise ExecutionBoundaryError(f"Unknown order intent: {intent_id}")
        return intent

    def list_active_intents(self) -> list[OrderIntent]:
        return self.order_intent_repository.list_by_statuses(list(IntentStatus.active_states()))

    def list_terminal_intents(self) -> list[OrderIntent]:
        return self.order_intent_repository.list_terminal()

    def list_all_intents(self) -> list[OrderIntent]:
        return self.order_intent_repository.list_all()

    def latest_terminal_intent(self) -> OrderIntent | None:
        return self.order_intent_repository.latest_by_statuses(list(IntentStatus.terminal_states()))

    def list_review_history(self, intent_id: str) -> list:
        return self.order_intent_repository.list_reviews(intent_id)

    def list_audit_history(self, intent_id: str) -> list:
        return self.audit_log.repository.list_for_entity(intent_id)

    def list_execution_history(self, intent_id: str) -> list[SimulatedExecution]:
        return self.order_intent_repository.list_executions(intent_id)

    def list_all_executions(self) -> list[SimulatedExecution]:
        return self.order_intent_repository.list_all_executions()

    def list_execution_timeline(self, intent_id: str) -> list[SimulatedFillEvent]:
        return self.order_intent_repository.list_fill_events(intent_id)

    def latest_simulated_execution(self, intent_id: str) -> SimulatedExecution | None:
        return self.order_intent_repository.latest_execution(intent_id)

    def latest_simulated_execution_overall(self) -> SimulatedExecution | None:
        return self.order_intent_repository.latest_execution_overall()

    def simulation_summary_for_intent(self, intent_id: str) -> SimulationSummary:
        return self.order_intent_repository.summarize_executions(intent_id)

    def simulation_summary_overall(self) -> SimulationSummary:
        return self.order_intent_repository.summarize_executions()

    def _record_review(
        self,
        intent_id: str,
        action: str,
        actor: str,
        note: str | None,
        payload: dict[str, object],
        created_at,
    ) -> None:
        self.order_intent_repository.save_review(
            review_id=new_id("ireview"),
            intent_id=intent_id,
            action=action,
            actor=actor,
            note=note,
            payload=payload,
            created_at=created_at.isoformat(),
        )

    def _simulation_payload(self, execution: SimulatedExecution) -> dict[str, object]:
        return {
            "execution_id": execution.execution_id,
            "status": execution.status.value,
            "accepted": execution.accepted,
            "order_id": execution.order_id,
            "reference_price": execution.reference_price,
            "best_bid": execution.best_bid,
            "best_ask": execution.best_ask,
            "simulated_price": execution.simulated_price,
            "slippage_bps": execution.slippage_bps,
            "filled_size_usd": execution.filled_size_usd,
            "fill_timestamp": execution.fill_timestamp.isoformat() if execution.fill_timestamp else None,
            "latency_ms": execution.latency_ms,
            "completion_reason": execution.completion_reason,
            "message": execution.message,
        }

    def _terminal_simulation_states(self) -> set[IntentStatus]:
        return {
            IntentStatus.SIMULATED_REJECTED,
            IntentStatus.SIMULATED_SUBMITTED,
            IntentStatus.SIMULATED_PARTIALLY_FILLED,
            IntentStatus.SIMULATED_FILLED,
            IntentStatus.SIMULATED_EXPIRED,
            IntentStatus.SIMULATED_CANCELLED,
        }
