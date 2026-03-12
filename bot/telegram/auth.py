from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_chat_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()
    chat_ids: set[int] = set()
    for item in raw_value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        chat_ids.add(int(stripped))
    return chat_ids


@dataclass(slots=True)
class TelegramOperatorAuth:
    allowed_chat_ids: set[int] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "TelegramOperatorAuth":
        return cls(allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")))

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.allowed_chat_ids

    def require_allowed(self, chat_id: int) -> None:
        if not self.is_allowed(chat_id):
            raise PermissionError("Unauthorized operator.")
