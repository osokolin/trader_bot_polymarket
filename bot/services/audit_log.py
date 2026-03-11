from __future__ import annotations

from datetime import datetime

from bot.domain.models import AuditEvent
from bot.storage.repositories import AuditRepository
from bot.utils.ids import new_id
from bot.utils.time import utc_now


class AuditLogService:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    def log(
        self,
        event_type: str,
        entity_id: str,
        message: str,
        payload: dict[str, object],
        created_at: datetime | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=new_id("audit"),
            event_type=event_type,
            entity_id=entity_id,
            message=message,
            payload=payload,
            created_at=created_at or utc_now(),
        )
        self.repository.save(event)
        return event
