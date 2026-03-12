from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.decisions import PolicyDecision
from bot.domain.enums import (
    AlertState,
    AlertSeverity,
    AlertType,
    IntentStatus,
    OperatorActionEntityType,
    OperatorActionRequestStatus,
    OperatorActionRequestType,
    PolicyRejectionReason,
    ProposalStatus,
    SourceType,
    TradeAction,
    WatchTargetType,
)
from bot.domain.models import (
    AuditEvent,
    DecisionReviewSnapshot,
    EvidenceRecord,
    ExecutionEvaluationSnapshot,
    Market,
    MarketDataSnapshot,
    OutcomeAnalysisGroup,
    OutcomeAnalysisSnapshot,
    OrderBookSnapshot,
    OperatorActionRequest,
    OperatorActionRequestRecord,
    ProbabilitySnapshot,
    ProbabilityEstimate,
    ResearchSummary,
    OperatorAlert,
    OrderIntent,
    Position,
    SavedView,
    SimulatedFillEvent,
    SimulatedExecution,
    SimulationSummary,
    TradeProposal,
    WatchlistEntry,
)

class OrderIntentRepository:
    ACTIVE_STATUSES = {status.value for status in IntentStatus.active_states()}

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, intent: OrderIntent) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO order_intents (
                intent_id, proposal_id, market_id, side, size_usd, limit_price, status,
                created_at, updated_at, reason, superseded_by_intent_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.intent_id,
                intent.proposal_id,
                intent.market_id,
                intent.side,
                intent.size_usd,
                intent.limit_price,
                intent.status.value,
                intent.created_at.isoformat(),
                intent.updated_at.isoformat(),
                intent.reason,
                intent.superseded_by_intent_id,
            ),
        )
        self.connection.commit()

    def get(self, intent_id: str) -> OrderIntent | None:
        row = self.connection.execute(
            "SELECT * FROM order_intents WHERE intent_id = ?",
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row_to_intent(row)

    def latest_state(self, intent_id: str) -> OrderIntent | None:
        return self.get(intent_id)

    def list_all(self) -> list[OrderIntent]:
        rows = self.connection.execute(
            "SELECT * FROM order_intents ORDER BY updated_at DESC"
        ).fetchall()
        return [self._row_to_intent(row) for row in rows]

    def list_active_for_proposal(self, proposal_id: str) -> list[OrderIntent]:
        placeholders = ", ".join("?" for _ in self.ACTIVE_STATUSES)
        rows = self.connection.execute(
            f"""
            SELECT * FROM order_intents
            WHERE proposal_id = ? AND status IN ({placeholders})
            ORDER BY created_at DESC
            """,
            (proposal_id, *self.ACTIVE_STATUSES),
        ).fetchall()
        return [self._row_to_intent(row) for row in rows]

    def latest_active_for_proposal(self, proposal_id: str) -> OrderIntent | None:
        intents = self.list_active_for_proposal(proposal_id)
        return intents[0] if intents else None

    def latest_by_statuses(self, statuses: list[IntentStatus]) -> OrderIntent | None:
        results = self.list_by_statuses(statuses)
        return results[0] if results else None

    def list_for_proposal(self, proposal_id: str) -> list[OrderIntent]:
        rows = self.connection.execute(
            """
            SELECT * FROM order_intents
            WHERE proposal_id = ?
            ORDER BY updated_at DESC
            """,
            (proposal_id,),
        ).fetchall()
        return [self._row_to_intent(row) for row in rows]

    def latest_for_proposal(self, proposal_id: str) -> OrderIntent | None:
        intents = self.list_for_proposal(proposal_id)
        return intents[0] if intents else None

    def list_by_statuses(self, statuses: list[IntentStatus]) -> list[OrderIntent]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = self.connection.execute(
            f"""
            SELECT * FROM order_intents
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            tuple(status.value for status in statuses),
        ).fetchall()
        return [self._row_to_intent(row) for row in rows]

    def list_terminal(self) -> list[OrderIntent]:
        return self.list_by_statuses(list(IntentStatus.terminal_states()))

    def save_review(
        self,
        review_id: str,
        intent_id: str,
        action: str,
        actor: str,
        note: str | None,
        payload: dict[str, object],
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO intent_reviews (
                review_id, intent_id, action, actor, note, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, intent_id, action, actor, note, json.dumps(payload), created_at),
        )
        self.connection.commit()

    def list_reviews(self, intent_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT review_id, action, actor, note, payload_json, created_at
            FROM intent_reviews
            WHERE intent_id = ?
            ORDER BY created_at DESC
            """,
            (intent_id,),
        ).fetchall()

    def save_execution(self, execution: SimulatedExecution) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO simulated_executions (
                execution_id, intent_id, status, accepted, order_id, reference_price,
                best_bid, best_ask, simulated_price, slippage_bps, filled_size_usd, fill_timestamp,
                latency_ms, completion_reason, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution.execution_id,
                execution.intent_id,
                execution.status.value,
                int(execution.accepted),
                execution.order_id,
                execution.reference_price,
                execution.best_bid,
                execution.best_ask,
                execution.simulated_price,
                execution.slippage_bps,
                execution.filled_size_usd,
                execution.fill_timestamp.isoformat() if execution.fill_timestamp else None,
                execution.latency_ms,
                execution.completion_reason,
                execution.message,
                execution.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_fill_events(self, events: list[SimulatedFillEvent]) -> None:
        for event in events:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO simulated_fill_events (
                    event_id, execution_id, intent_id, event_type, fragment_index, price, size_usd,
                    remaining_size_usd, latency_ms, event_timestamp, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.execution_id,
                    event.intent_id,
                    event.event_type,
                    event.fragment_index,
                    event.price,
                    event.size_usd,
                    event.remaining_size_usd,
                    event.latency_ms,
                    event.event_timestamp.isoformat(),
                    event.message,
                ),
            )
        self.connection.commit()

    def list_executions(self, intent_id: str) -> list[SimulatedExecution]:
        rows = self.connection.execute(
            """
            SELECT execution_id, intent_id, status, accepted, order_id, reference_price, best_bid,
                   best_ask, simulated_price, slippage_bps, filled_size_usd, fill_timestamp,
                   latency_ms, completion_reason, message, created_at
            FROM simulated_executions
            WHERE intent_id = ?
            ORDER BY created_at DESC
            """,
            (intent_id,),
        ).fetchall()
        return [self._row_to_execution(row) for row in rows]

    def latest_execution(self, intent_id: str) -> SimulatedExecution | None:
        items = self.list_executions(intent_id)
        return items[0] if items else None

    def latest_execution_overall(self) -> SimulatedExecution | None:
        items = self.list_all_executions()
        return items[0] if items else None

    def list_all_executions(self) -> list[SimulatedExecution]:
        rows = self.connection.execute(
            """
            SELECT execution_id, intent_id, status, accepted, order_id, reference_price, best_bid,
                   best_ask, simulated_price, slippage_bps, filled_size_usd, fill_timestamp,
                   latency_ms, completion_reason, message, created_at
            FROM simulated_executions
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_execution(row) for row in rows]

    def list_fill_events(self, intent_id: str) -> list[SimulatedFillEvent]:
        rows = self.connection.execute(
            """
            SELECT event_id, execution_id, intent_id, event_type, fragment_index, price, size_usd,
                   remaining_size_usd, latency_ms, event_timestamp, message
            FROM simulated_fill_events
            WHERE intent_id = ?
            ORDER BY event_timestamp ASC, fragment_index ASC
            """,
            (intent_id,),
        ).fetchall()
        return [self._row_to_fill_event(row) for row in rows]

    def summarize_executions(self, intent_id: str | None = None) -> SimulationSummary:
        executions = self.list_executions(intent_id) if intent_id is not None else self.list_all_executions()
        return self._build_summary("intent" if intent_id is not None else "all", executions)

    def _row_to_intent(self, row: sqlite3.Row) -> OrderIntent:
        return OrderIntent(
            intent_id=row["intent_id"],
            proposal_id=row["proposal_id"],
            market_id=row["market_id"],
            side=row["side"],
            size_usd=row["size_usd"],
            limit_price=row["limit_price"],
            status=IntentStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            reason=row["reason"],
            superseded_by_intent_id=row["superseded_by_intent_id"],
        )

    def _row_to_execution(self, row: sqlite3.Row) -> SimulatedExecution:
        return SimulatedExecution(
            execution_id=row["execution_id"],
            intent_id=row["intent_id"],
            status=IntentStatus(row["status"]),
            accepted=bool(row["accepted"]),
            order_id=row["order_id"],
            reference_price=row["reference_price"],
            best_bid=row["best_bid"],
            best_ask=row["best_ask"],
            simulated_price=row["simulated_price"],
            slippage_bps=row["slippage_bps"],
            filled_size_usd=row["filled_size_usd"],
            fill_timestamp=datetime.fromisoformat(row["fill_timestamp"]) if row["fill_timestamp"] else None,
            latency_ms=row["latency_ms"],
            completion_reason=row["completion_reason"],
            message=row["message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_fill_event(self, row: sqlite3.Row) -> SimulatedFillEvent:
        return SimulatedFillEvent(
            event_id=row["event_id"],
            execution_id=row["execution_id"],
            intent_id=row["intent_id"],
            event_type=row["event_type"],
            fragment_index=row["fragment_index"],
            price=row["price"],
            size_usd=row["size_usd"],
            remaining_size_usd=row["remaining_size_usd"],
            latency_ms=row["latency_ms"],
            event_timestamp=datetime.fromisoformat(row["event_timestamp"]),
            message=row["message"],
        )

    def _build_summary(self, scope: str, executions: list[SimulatedExecution]) -> SimulationSummary:
        slippages = [item.slippage_bps for item in executions if item.slippage_bps is not None]
        latest_fill = max((item.fill_timestamp for item in executions if item.fill_timestamp is not None), default=None)
        return SimulationSummary(
            scope=scope,
            execution_count=len(executions),
            accepted_count=sum(1 for item in executions if item.accepted),
            filled_count=sum(1 for item in executions if item.status == IntentStatus.SIMULATED_FILLED),
            partial_fill_count=sum(1 for item in executions if item.status == IntentStatus.SIMULATED_PARTIALLY_FILLED),
            resting_count=sum(1 for item in executions if item.status == IntentStatus.SIMULATED_SUBMITTED),
            rejected_count=sum(
                1
                for item in executions
                if item.status
                in {
                    IntentStatus.SIMULATED_REJECTED,
                    IntentStatus.SIMULATED_EXPIRED,
                    IntentStatus.SIMULATED_CANCELLED,
                }
            ),
            total_filled_size_usd=round(sum(item.filled_size_usd for item in executions), 2),
            average_slippage_bps=None if not slippages else round(sum(slippages) / len(slippages), 2),
            latest_fill_timestamp=latest_fill,
        )


class PositionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, position: Position) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO positions (
                position_id, market_id, size_usd, entry_price, status, theme, opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.position_id,
                position.market_id,
                position.size_usd,
                position.entry_price,
                position.status.value,
                position.theme,
                position.opened_at.isoformat(),
            ),
        )
        self.connection.commit()

    def count_open(self) -> int:
        cursor = self.connection.execute(
            "SELECT COUNT(*) FROM positions WHERE status = 'open'"
        )
        return int(cursor.fetchone()[0])

    def unresolved_exposure(self) -> float:
        cursor = self.connection.execute(
            "SELECT COALESCE(SUM(size_usd), 0) FROM positions WHERE status = 'open'"
        )
        return float(cursor.fetchone()[0] or 0.0)
