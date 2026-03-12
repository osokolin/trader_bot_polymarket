from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.decisions import PolicyDecision
from bot.domain.enums import (
    PolicyRejectionReason,
    ProposalStatus,
    SourceType,
    TradeAction,
)
from bot.domain.models import (
    AuditEvent,
    TradeProposal,
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
