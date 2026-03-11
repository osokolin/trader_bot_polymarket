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


class ProposalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, proposal: TradeProposal) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO trade_proposals (
                proposal_id, market_id, market_title, market_category, status, action, side, market_price,
                fair_probability, edge, confidence, model_agreement, trusted_source_present, source_types_json,
                current_size_usd, current_limit_price,
                recommended_size_usd, max_allowed_size_usd, suggested_limit_price, thesis_json, risks_json,
                policy_allowed, policy_reasons_json, policy_details_json, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                proposal.market_id,
                proposal.market_title,
                proposal.market_category,
                proposal.status.value,
                proposal.action.value,
                proposal.side,
                proposal.market_price,
                proposal.fair_probability,
                proposal.edge,
                proposal.confidence,
                proposal.model_agreement,
                int(proposal.trusted_source_present),
                json.dumps([item.value for item in proposal.source_types]),
                proposal.current_size_usd,
                proposal.current_limit_price,
                proposal.recommended_size_usd,
                proposal.max_allowed_size_usd,
                proposal.suggested_limit_price,
                json.dumps(proposal.thesis),
                json.dumps(proposal.risks),
                int(proposal.policy_decision.allowed),
                json.dumps([item.value for item in proposal.policy_decision.reasons]),
                json.dumps(proposal.policy_decision.details),
                proposal.created_at.isoformat(),
                proposal.updated_at.isoformat(),
                proposal.expires_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get(self, proposal_id: str) -> TradeProposal | None:
        row = self.connection.execute(
            "SELECT * FROM trade_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        return None if row is None else self._row_to_proposal(row)

    def list_all(self) -> list[TradeProposal]:
        rows = self.connection.execute(
            "SELECT * FROM trade_proposals ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def list_by_statuses(self, statuses: list[ProposalStatus]) -> list[TradeProposal]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = self.connection.execute(
            f"""
            SELECT * FROM trade_proposals
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            tuple(status.value for status in statuses),
        ).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def latest_state(self, proposal_id: str) -> TradeProposal | None:
        return self.get(proposal_id)

    def latest_by_statuses(self, statuses: list[ProposalStatus]) -> TradeProposal | None:
        results = self.list_by_statuses(statuses)
        return results[0] if results else None

    def list_for_market(self, market_id: str) -> list[TradeProposal]:
        rows = self.connection.execute(
            """
            SELECT * FROM trade_proposals
            WHERE market_id = ?
            ORDER BY updated_at DESC
            """,
            (market_id,),
        ).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def latest_for_market(self, market_id: str) -> TradeProposal | None:
        proposals = self.list_for_market(market_id)
        return proposals[0] if proposals else None

    def save_review(
        self,
        review_id: str,
        proposal_id: str,
        action: str,
        actor: str,
        note: str | None,
        payload: dict[str, object],
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO proposal_reviews (
                review_id, proposal_id, action, actor, note, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, proposal_id, action, actor, note, json.dumps(payload), created_at),
        )
        self.connection.commit()

    def list_reviews(self, proposal_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT review_id, action, actor, note, payload_json, created_at
            FROM proposal_reviews
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            """,
            (proposal_id,),
        ).fetchall()

    def _row_to_proposal(self, row: sqlite3.Row) -> TradeProposal:
        return TradeProposal(
            proposal_id=row["proposal_id"],
            market_id=row["market_id"],
            market_title=row["market_title"],
            market_category=row["market_category"],
            action=TradeAction(row["action"]),
            side=row["side"],
            market_price=row["market_price"],
            fair_probability=row["fair_probability"],
            edge=row["edge"],
            confidence=row["confidence"],
            model_agreement=row["model_agreement"],
            trusted_source_present=bool(row["trusted_source_present"]),
            source_types=[SourceType(item) for item in json.loads(row["source_types_json"])],
            current_size_usd=row["current_size_usd"],
            current_limit_price=row["current_limit_price"],
            recommended_size_usd=row["recommended_size_usd"],
            max_allowed_size_usd=row["max_allowed_size_usd"],
            suggested_limit_price=row["suggested_limit_price"],
            thesis=json.loads(row["thesis_json"]),
            risks=json.loads(row["risks_json"]),
            status=ProposalStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            policy_decision=PolicyDecision(
                allowed=bool(row["policy_allowed"]),
                reasons=[PolicyRejectionReason(item) for item in json.loads(row["policy_reasons_json"])],
                details=json.loads(row["policy_details_json"]),
            ),
        )


class AuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, event: AuditEvent) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO audit_events (
                event_id, event_type, entity_id, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.entity_id,
                event.message,
                json.dumps(event.payload),
                event.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def list_for_entity(self, entity_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT event_id, event_type, message, payload_json, created_at
            FROM audit_events
            WHERE entity_id = ?
            ORDER BY created_at DESC
            """,
            (entity_id,),
        ).fetchall()


class MarketDataSnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: MarketDataSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO market_data_snapshots (
                snapshot_id, market_id, asset_id, source, market_payload_json, orderbook_payload_json,
                websocket_payload_json, last_trade_price, data_age_seconds, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.market_id,
                snapshot.asset_id,
                snapshot.source,
                json.dumps(self._market_payload(snapshot.market)),
                json.dumps(self._orderbook_payload(snapshot.orderbook)),
                json.dumps(snapshot.websocket_payload),
                snapshot.last_trade_price,
                snapshot.data_age_seconds,
                snapshot.fetched_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_market(self, market_id: str) -> MarketDataSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM market_data_snapshots
            WHERE market_id = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_for_market(self, market_id: str, limit: int = 20) -> list[MarketDataSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM market_data_snapshots
            WHERE market_id = ?
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (market_id, limit),
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> MarketDataSnapshot:
        market_payload = json.loads(row["market_payload_json"])
        orderbook_payload = json.loads(row["orderbook_payload_json"])
        return MarketDataSnapshot(
            snapshot_id=row["snapshot_id"],
            market_id=row["market_id"],
            asset_id=row["asset_id"],
            market=Market(
                market_id=market_payload["market_id"],
                title=market_payload["title"],
                category=market_payload["category"],
                liquidity_usd=market_payload["liquidity_usd"],
                spread_pct=market_payload["spread_pct"],
                resolution_time=datetime.fromisoformat(market_payload["resolution_time"]),
                rules_text=market_payload["rules_text"],
                rules_confidence=market_payload["rules_confidence"],
                tags=market_payload["tags"],
                has_orderbook=market_payload["has_orderbook"],
                event_id=market_payload.get("event_id"),
                outcome_token_id=market_payload.get("outcome_token_id"),
                active=market_payload.get("active", True),
                closed=market_payload.get("closed", False),
                archived=market_payload.get("archived", False),
                last_traded_price=market_payload.get("last_traded_price"),
            ),
            orderbook=OrderBookSnapshot(
                market_id=orderbook_payload["market_id"],
                best_bid=orderbook_payload["best_bid"],
                best_ask=orderbook_payload["best_ask"],
                midpoint=orderbook_payload["midpoint"],
                spread_pct=orderbook_payload["spread_pct"],
                timestamp=datetime.fromisoformat(orderbook_payload["timestamp"]),
            ),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            source=row["source"],
            data_age_seconds=row["data_age_seconds"],
            last_trade_price=row["last_trade_price"],
            websocket_payload=json.loads(row["websocket_payload_json"]),
        )

    def _market_payload(self, market: Market) -> dict[str, object]:
        return {
            "market_id": market.market_id,
            "title": market.title,
            "category": market.category,
            "liquidity_usd": market.liquidity_usd,
            "spread_pct": market.spread_pct,
            "resolution_time": market.resolution_time.isoformat(),
            "rules_text": market.rules_text,
            "rules_confidence": market.rules_confidence,
            "tags": market.tags,
            "has_orderbook": market.has_orderbook,
            "event_id": market.event_id,
            "outcome_token_id": market.outcome_token_id,
            "active": market.active,
            "closed": market.closed,
            "archived": market.archived,
            "last_traded_price": market.last_traded_price,
        }

    def _orderbook_payload(self, orderbook: OrderBookSnapshot) -> dict[str, object]:
        return {
            "market_id": orderbook.market_id,
            "best_bid": orderbook.best_bid,
            "best_ask": orderbook.best_ask,
            "midpoint": orderbook.midpoint,
            "spread_pct": orderbook.spread_pct,
            "timestamp": orderbook.timestamp.isoformat(),
        }


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


class WatchlistRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, entry: WatchlistEntry) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO watchlist_entries (
                watch_id, target_type, target_id, label, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry.watch_id,
                entry.target_type.value,
                entry.target_id,
                entry.label,
                entry.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def delete(self, target_type: WatchTargetType, target_id: str) -> None:
        self.connection.execute(
            "DELETE FROM watchlist_entries WHERE target_type = ? AND target_id = ?",
            (target_type.value, target_id),
        )
        self.connection.commit()

    def list_all(self) -> list[WatchlistEntry]:
        rows = self.connection.execute(
            """
            SELECT watch_id, target_type, target_id, label, created_at
            FROM watchlist_entries
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def list_by_type(self, target_type: WatchTargetType) -> list[WatchlistEntry]:
        rows = self.connection.execute(
            """
            SELECT watch_id, target_type, target_id, label, created_at
            FROM watchlist_entries
            WHERE target_type = ?
            ORDER BY created_at DESC
            """,
            (target_type.value,),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: sqlite3.Row) -> WatchlistEntry:
        return WatchlistEntry(
            watch_id=row["watch_id"],
            target_type=WatchTargetType(row["target_type"]),
            target_id=row["target_id"],
            label=row["label"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class AlertRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, alert: OperatorAlert) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO operator_alerts (
                alert_id, alert_type, severity, state, entity_type, entity_id,
                related_market_id, related_proposal_id, summary, payload_json, created_at,
                acknowledged_at, dismissed_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.alert_id,
                alert.alert_type.value,
                alert.severity.value,
                alert.state.value,
                alert.entity_type.value,
                alert.entity_id,
                alert.related_market_id,
                alert.related_proposal_id,
                alert.summary,
                json.dumps(alert.payload),
                alert.created_at.isoformat(),
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                alert.dismissed_at.isoformat() if alert.dismissed_at else None,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
            ),
        )
        self.connection.commit()

    def get(self, alert_id: str) -> OperatorAlert | None:
        row = self.connection.execute(
            """
            SELECT alert_id, alert_type, severity, state, entity_type, entity_id, related_market_id,
                   related_proposal_id, summary, payload_json, created_at, acknowledged_at, dismissed_at, resolved_at
            FROM operator_alerts
            WHERE alert_id = ?
            """,
            (alert_id,),
        ).fetchone()
        return None if row is None else self._row_to_alert(row)

    def list_all(self, state: AlertState | None = None) -> list[OperatorAlert]:
        sql = """
            SELECT alert_id, alert_type, severity, state, entity_type, entity_id, related_market_id,
                   related_proposal_id, summary, payload_json, created_at, acknowledged_at, dismissed_at, resolved_at
            FROM operator_alerts
        """
        params: tuple[object, ...] = ()
        if state is not None:
            sql += " WHERE state = ?"
            params = (state.value,)
        sql += " ORDER BY created_at DESC"
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def list_for_entity(self, entity_type: WatchTargetType, entity_id: str) -> list[OperatorAlert]:
        rows = self.connection.execute(
            """
            SELECT alert_id, alert_type, severity, state, entity_type, entity_id, related_market_id,
                   related_proposal_id, summary, payload_json, created_at, acknowledged_at, dismissed_at, resolved_at
            FROM operator_alerts
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC
            """,
            (entity_type.value, entity_id),
        ).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def find_active_by_type_and_entity(
        self,
        alert_type: AlertType,
        entity_type: WatchTargetType,
        entity_id: str,
    ) -> OperatorAlert | None:
        row = self.connection.execute(
            """
            SELECT alert_id, alert_type, severity, state, entity_type, entity_id, related_market_id,
                   related_proposal_id, summary, payload_json, created_at, acknowledged_at, dismissed_at, resolved_at
            FROM operator_alerts
            WHERE alert_type = ? AND entity_type = ? AND entity_id = ? AND state IN (?, ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (
                alert_type.value,
                entity_type.value,
                entity_id,
                AlertState.OPEN.value,
                AlertState.ACKNOWLEDGED.value,
            ),
        ).fetchone()
        return None if row is None else self._row_to_alert(row)

    def exists_recent(
        self,
        alert_type: AlertType,
        entity_type: WatchTargetType,
        entity_id: str,
        created_at: datetime,
    ) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM operator_alerts
            WHERE alert_type = ? AND entity_type = ? AND entity_id = ? AND created_at = ?
            LIMIT 1
            """,
            (alert_type.value, entity_type.value, entity_id, created_at.isoformat()),
        ).fetchone()
        return row is not None

    def _row_to_alert(self, row: sqlite3.Row) -> OperatorAlert:
        return OperatorAlert(
            alert_id=row["alert_id"],
            alert_type=AlertType(row["alert_type"]),
            severity=AlertSeverity(row["severity"]),
            state=AlertState(row["state"]),
            entity_type=WatchTargetType(row["entity_type"]),
            entity_id=row["entity_id"],
            related_market_id=row["related_market_id"],
            related_proposal_id=row["related_proposal_id"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            dismissed_at=datetime.fromisoformat(row["dismissed_at"]) if row["dismissed_at"] else None,
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        )


class SavedViewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, saved_view: SavedView) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO saved_views (view_id, name, kind, params_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                saved_view.view_id,
                saved_view.name,
                saved_view.kind,
                json.dumps(saved_view.params, sort_keys=True),
                saved_view.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_by_name(self, name: str) -> SavedView | None:
        row = self.connection.execute(
            """
            SELECT view_id, name, kind, params_json, created_at
            FROM saved_views
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        return None if row is None else self._row_to_saved_view(row)

    def list_all(self) -> list[SavedView]:
        rows = self.connection.execute(
            """
            SELECT view_id, name, kind, params_json, created_at
            FROM saved_views
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_saved_view(row) for row in rows]

    def _row_to_saved_view(self, row: sqlite3.Row) -> SavedView:
        return SavedView(
            view_id=row["view_id"],
            name=row["name"],
            kind=row["kind"],
            params=json.loads(row["params_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class ProbabilitySnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: ProbabilitySnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO probability_snapshots (
                snapshot_id, market_id, proposal_id, fair_probability, confidence, model_agreement,
                trusted_source_present, source_types_json, key_factors_json, source_count,
                confidence_components_json, explanation, source_inputs_json, evidence_records_json,
                source_type_contributions_json, research_summary, research_key_factors_json,
                thesis_points_json, risk_points_json, evidence_summary_json, current_price,
                data_age_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.market_id,
                snapshot.proposal_id,
                snapshot.probability.fair_probability,
                snapshot.probability.confidence,
                snapshot.probability.model_agreement,
                int(snapshot.probability.trusted_source_present),
                json.dumps([item.value for item in snapshot.probability.source_types]),
                json.dumps(snapshot.probability.key_factors),
                snapshot.probability.source_count,
                json.dumps(snapshot.probability.confidence_components),
                snapshot.probability.explanation,
                json.dumps(snapshot.probability.source_inputs),
                json.dumps(
                    [
                        {
                            "source_id": item.source_id,
                            "source_name": item.source_name,
                            "source_type": item.source_type.value,
                            "weight": item.weight,
                            "contribution": item.contribution,
                            "summary": item.summary,
                            "supports_trade": item.supports_trade,
                        }
                        for item in snapshot.probability.evidence_records
                    ]
                ),
                json.dumps(snapshot.probability.source_type_contributions, sort_keys=True),
                snapshot.research_summary.summary,
                json.dumps(snapshot.research_summary.key_factors),
                json.dumps(snapshot.research_summary.thesis_points),
                json.dumps(snapshot.research_summary.risk_points),
                json.dumps(snapshot.research_summary.evidence_summary),
                snapshot.current_price,
                snapshot.data_age_seconds,
                snapshot.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_proposal(self, proposal_id: str) -> ProbabilitySnapshot | None:
        items = self.list_for_proposal(proposal_id, limit=1)
        return items[0] if items else None

    def latest_for_market(self, market_id: str) -> ProbabilitySnapshot | None:
        items = self.list_for_market(market_id, limit=1)
        return items[0] if items else None

    def list_for_proposal(self, proposal_id: str, limit: int | None = None) -> list[ProbabilitySnapshot]:
        sql = """
            SELECT * FROM probability_snapshots
            WHERE proposal_id = ?
            ORDER BY created_at DESC
        """
        params: tuple[object, ...] = (proposal_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (proposal_id, limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def list_for_market(self, market_id: str, limit: int | None = None) -> list[ProbabilitySnapshot]:
        sql = """
            SELECT * FROM probability_snapshots
            WHERE market_id = ?
            ORDER BY created_at DESC
        """
        params: tuple[object, ...] = (market_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (market_id, limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> ProbabilitySnapshot:
        probability = ProbabilityEstimate(
            market_id=row["market_id"],
            fair_probability=row["fair_probability"],
            confidence=row["confidence"],
            model_agreement=row["model_agreement"],
            trusted_source_present=bool(row["trusted_source_present"]),
            source_types=[SourceType(item) for item in json.loads(row["source_types_json"])],
            key_factors=json.loads(row["key_factors_json"]),
            source_count=row["source_count"],
            confidence_components=json.loads(row["confidence_components_json"]),
            explanation=row["explanation"],
            source_inputs=json.loads(row["source_inputs_json"]),
            evidence_records=[
                EvidenceRecord(
                    source_id=item["source_id"],
                    source_name=item["source_name"],
                    source_type=SourceType(item["source_type"]),
                    weight=item["weight"],
                    contribution=item["contribution"],
                    summary=item["summary"],
                    supports_trade=item.get("supports_trade", True),
                )
                for item in json.loads(row["evidence_records_json"])
            ],
            source_type_contributions=json.loads(row["source_type_contributions_json"]),
        )
        research = ResearchSummary(
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            summary=row["research_summary"],
            key_factors=json.loads(row["research_key_factors_json"]),
            thesis_points=json.loads(row["thesis_points_json"]),
            risk_points=json.loads(row["risk_points_json"]),
            source_count=row["source_count"],
            evidence_summary=json.loads(row["evidence_summary_json"]),
        )
        return ProbabilitySnapshot(
            snapshot_id=row["snapshot_id"],
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            probability=probability,
            research_summary=research,
            current_price=row["current_price"],
            data_age_seconds=row["data_age_seconds"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class DecisionReviewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, review: DecisionReviewSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO decision_reviews (
                review_id, scope, market_id, proposal_id, probability_snapshot_id, previous_snapshot_id,
                intent_id, execution_id, confidence_outcome, probability_outcome, execution_outcome,
                summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.review_id,
                review.scope,
                review.market_id,
                review.proposal_id,
                review.probability_snapshot_id,
                review.previous_snapshot_id,
                review.intent_id,
                review.execution_id,
                review.confidence_outcome,
                review.probability_outcome,
                review.execution_outcome,
                review.summary,
                json.dumps(review.payload),
                review.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_proposal(self, proposal_id: str) -> DecisionReviewSnapshot | None:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (proposal_id,),
        ).fetchone()
        return None if rows is None else self._row_to_snapshot(rows)

    def latest_for_market(self, market_id: str) -> DecisionReviewSnapshot | None:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            WHERE market_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        return None if rows is None else self._row_to_snapshot(rows)

    def list_all(self) -> list[DecisionReviewSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM decision_reviews
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> DecisionReviewSnapshot:
        return DecisionReviewSnapshot(
            review_id=row["review_id"],
            scope=row["scope"],
            market_id=row["market_id"],
            proposal_id=row["proposal_id"],
            probability_snapshot_id=row["probability_snapshot_id"],
            previous_snapshot_id=row["previous_snapshot_id"],
            intent_id=row["intent_id"],
            execution_id=row["execution_id"],
            confidence_outcome=row["confidence_outcome"],
            probability_outcome=row["probability_outcome"],
            execution_outcome=row["execution_outcome"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class ExecutionEvaluationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, evaluation: ExecutionEvaluationSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO execution_evaluations (
                evaluation_id, proposal_id, intent_id, execution_id, verdict, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation.evaluation_id,
                evaluation.proposal_id,
                evaluation.intent_id,
                evaluation.execution_id,
                evaluation.verdict,
                evaluation.summary,
                json.dumps(evaluation.payload),
                evaluation.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest_for_intent(self, intent_id: str) -> ExecutionEvaluationSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            WHERE intent_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def latest_for_proposal(self, proposal_id: str) -> ExecutionEvaluationSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (proposal_id,),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_all(self) -> list[ExecutionEvaluationSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_evaluations
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> ExecutionEvaluationSnapshot:
        return ExecutionEvaluationSnapshot(
            evaluation_id=row["evaluation_id"],
            proposal_id=row["proposal_id"],
            intent_id=row["intent_id"],
            execution_id=row["execution_id"],
            verdict=row["verdict"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class OutcomeAnalysisRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, snapshot: OutcomeAnalysisSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO outcome_analysis_snapshots (
                snapshot_id, scope, group_by, since_hours, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.scope,
                snapshot.group_by,
                snapshot.since_hours,
                snapshot.summary,
                json.dumps(
                    {
                        "groups": [
                            {
                                "group_by": item.group_by,
                                "group_value": item.group_value,
                                "review_count": item.review_count,
                                "evaluation_count": item.evaluation_count,
                                "average_fair_probability_delta": item.average_fair_probability_delta,
                                "average_confidence_delta": item.average_confidence_delta,
                                "confidence_held_count": item.confidence_held_count,
                                "confidence_degraded_count": item.confidence_degraded_count,
                                "probability_in_favor_count": item.probability_in_favor_count,
                                "probability_against_count": item.probability_against_count,
                                "execution_favorable_count": item.execution_favorable_count,
                                "execution_unfavorable_count": item.execution_unfavorable_count,
                                "verdict_counts": item.verdict_counts,
                            }
                            for item in snapshot.groups
                        ]
                    }
                ),
                snapshot.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def latest(self, scope: str, group_by: str) -> OutcomeAnalysisSnapshot | None:
        row = self.connection.execute(
            """
            SELECT * FROM outcome_analysis_snapshots
            WHERE scope = ? AND group_by = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (scope, group_by),
        ).fetchone()
        return None if row is None else self._row_to_snapshot(row)

    def list_all(self) -> list[OutcomeAnalysisSnapshot]:
        rows = self.connection.execute(
            """
            SELECT * FROM outcome_analysis_snapshots
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def _row_to_snapshot(self, row: sqlite3.Row) -> OutcomeAnalysisSnapshot:
        payload = json.loads(row["payload_json"])
        return OutcomeAnalysisSnapshot(
            snapshot_id=row["snapshot_id"],
            scope=row["scope"],
            group_by=row["group_by"],
            since_hours=row["since_hours"],
            groups=[
                OutcomeAnalysisGroup(
                    group_by=item["group_by"],
                    group_value=item["group_value"],
                    review_count=item["review_count"],
                    evaluation_count=item["evaluation_count"],
                    average_fair_probability_delta=item["average_fair_probability_delta"],
                    average_confidence_delta=item["average_confidence_delta"],
                    confidence_held_count=item["confidence_held_count"],
                    confidence_degraded_count=item["confidence_degraded_count"],
                    probability_in_favor_count=item["probability_in_favor_count"],
                    probability_against_count=item["probability_against_count"],
                    execution_favorable_count=item["execution_favorable_count"],
                    execution_unfavorable_count=item["execution_unfavorable_count"],
                    verdict_counts=item["verdict_counts"],
                )
                for item in payload["groups"]
            ],
            summary=row["summary"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
