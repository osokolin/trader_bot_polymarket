from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.enums import (
    AlertState,
    AlertSeverity,
    AlertType,
    WatchTargetType,
)
from bot.domain.models import (
    OperatorAlert,
    WatchlistEntry,
)

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

    def find_any_by_type_and_entity(
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
            WHERE alert_type = ? AND entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (alert_type.value, entity_type.value, entity_id),
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
