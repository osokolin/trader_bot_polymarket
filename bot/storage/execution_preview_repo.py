from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bot.domain.enums import ExecutionPreviewStatus
from bot.domain.models import ExecutionPreview


class ExecutionPreviewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, preview: ExecutionPreview) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO execution_previews (
                preview_id, proposal_id, source, status, dry_run, market_id, event_id, condition_id,
                token_id, side, intended_price, quoted_price, intended_size_usd, normalized_size_usd,
                estimated_shares, warnings_json, validation_errors_json, preview_payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preview.preview_id,
                preview.proposal_id,
                preview.source,
                preview.status.value,
                int(preview.dry_run),
                preview.market_id,
                preview.event_id,
                preview.condition_id,
                preview.token_id,
                preview.side,
                preview.intended_price,
                preview.quoted_price,
                preview.intended_size_usd,
                preview.normalized_size_usd,
                preview.estimated_shares,
                json.dumps(preview.warnings),
                json.dumps(preview.validation_errors),
                json.dumps(preview.preview_payload, sort_keys=True),
                preview.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def list_recent(self, limit: int = 20) -> list[ExecutionPreview]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_previews
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_preview(row) for row in rows]

    def list_for_proposal(self, proposal_id: str, limit: int = 20) -> list[ExecutionPreview]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_previews
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (proposal_id, limit),
        ).fetchall()
        return [self._row_to_preview(row) for row in rows]

    def list_failed(self, limit: int = 20) -> list[ExecutionPreview]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_previews
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (ExecutionPreviewStatus.BLOCKED.value, limit),
        ).fetchall()
        return [self._row_to_preview(row) for row in rows]

    def list_with_warnings(self, limit: int = 20) -> list[ExecutionPreview]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_previews
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (ExecutionPreviewStatus.READY_WITH_WARNINGS.value, limit),
        ).fetchall()
        return [self._row_to_preview(row) for row in rows]

    def list_all(self) -> list[ExecutionPreview]:
        rows = self.connection.execute(
            """
            SELECT * FROM execution_previews
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [self._row_to_preview(row) for row in rows]

    def _row_to_preview(self, row: sqlite3.Row) -> ExecutionPreview:
        return ExecutionPreview(
            preview_id=row["preview_id"],
            proposal_id=row["proposal_id"],
            source=row["source"],
            dry_run=bool(row["dry_run"]),
            market_id=row["market_id"],
            event_id=row["event_id"],
            condition_id=row["condition_id"],
            token_id=row["token_id"],
            side=row["side"],
            intended_price=row["intended_price"],
            quoted_price=row["quoted_price"],
            intended_size_usd=row["intended_size_usd"],
            normalized_size_usd=row["normalized_size_usd"],
            estimated_shares=row["estimated_shares"],
            status=ExecutionPreviewStatus(row["status"]),
            warnings=json.loads(row["warnings_json"]),
            validation_errors=json.loads(row["validation_errors_json"]),
            preview_payload=json.loads(row["preview_payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
