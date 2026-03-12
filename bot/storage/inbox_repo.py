from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.enums import (
    OperatorActionEntityType,
    OperatorActionRequestStatus,
    OperatorActionRequestType,
)
from bot.domain.models import (
    OperatorActionRequest,
    OperatorActionRequestRecord,
)

class OperatorActionRequestRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, request: OperatorActionRequest) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO operator_action_requests (
                request_id, request_type, entity_type, entity_id, status, title, summary, payload_json,
                created_at, updated_at, actioned_at, actioned_by, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.request_type.value,
                request.entity_type.value,
                request.entity_id,
                request.status.value,
                request.title,
                request.summary,
                json.dumps(request.payload),
                request.created_at.isoformat(),
                request.updated_at.isoformat(),
                request.actioned_at.isoformat() if request.actioned_at else None,
                request.actioned_by,
                request.source,
            ),
        )
        self.connection.commit()

    def get(self, request_id: str) -> OperatorActionRequest | None:
        row = self.connection.execute(
            """
            SELECT request_id, request_type, entity_type, entity_id, status, title, summary, payload_json,
                   created_at, updated_at, actioned_at, actioned_by, source
            FROM operator_action_requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        return None if row is None else self._row_to_request(row)

    def list_by_statuses(self, statuses: list[OperatorActionRequestStatus]) -> list[OperatorActionRequest]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = self.connection.execute(
            f"""
            SELECT request_id, request_type, entity_type, entity_id, status, title, summary, payload_json,
                   created_at, updated_at, actioned_at, actioned_by, source
            FROM operator_action_requests
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            tuple(status.value for status in statuses),
        ).fetchall()
        return [self._row_to_request(row) for row in rows]

    def find_active_by_type_and_entity(
        self,
        request_type: OperatorActionRequestType,
        entity_type: OperatorActionEntityType,
        entity_id: str,
    ) -> OperatorActionRequest | None:
        row = self.connection.execute(
            """
            SELECT request_id, request_type, entity_type, entity_id, status, title, summary, payload_json,
                   created_at, updated_at, actioned_at, actioned_by, source
            FROM operator_action_requests
            WHERE request_type = ? AND entity_type = ? AND entity_id = ? AND status IN (?, ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                request_type.value,
                entity_type.value,
                entity_id,
                OperatorActionRequestStatus.OPEN.value,
                OperatorActionRequestStatus.ACKNOWLEDGED.value,
            ),
        ).fetchone()
        return None if row is None else self._row_to_request(row)

    def record_action(self, record: OperatorActionRequestRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO operator_action_request_records (
                record_id, request_id, action, actor, result, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.record_id,
                record.request_id,
                record.action,
                record.actor,
                record.result,
                json.dumps(record.payload),
                record.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def list_actions(self, request_id: str) -> list[OperatorActionRequestRecord]:
        rows = self.connection.execute(
            """
            SELECT record_id, request_id, action, actor, result, payload_json, created_at
            FROM operator_action_request_records
            WHERE request_id = ?
            ORDER BY created_at DESC
            """,
            (request_id,),
        ).fetchall()
        return [self._row_to_action_record(row) for row in rows]

    def _row_to_request(self, row: sqlite3.Row) -> OperatorActionRequest:
        return OperatorActionRequest(
            request_id=row["request_id"],
            request_type=OperatorActionRequestType(row["request_type"]),
            entity_type=OperatorActionEntityType(row["entity_type"]),
            entity_id=row["entity_id"],
            status=OperatorActionRequestStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            actioned_at=datetime.fromisoformat(row["actioned_at"]) if row["actioned_at"] else None,
            actioned_by=row["actioned_by"],
            source=row["source"],
        )

    def _row_to_action_record(self, row: sqlite3.Row) -> OperatorActionRequestRecord:
        return OperatorActionRequestRecord(
            record_id=row["record_id"],
            request_id=row["request_id"],
            action=row["action"],
            actor=row["actor"],
            result=row["result"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
