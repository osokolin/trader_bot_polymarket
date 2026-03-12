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
