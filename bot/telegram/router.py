from __future__ import annotations

from dataclasses import dataclass

from bot.telegram import formatter
from bot.telegram.auth import TelegramOperatorAuth
from bot.services.telegram_operator_service import TelegramOperatorService


@dataclass(slots=True)
class TelegramOutboundMessage:
    chat_id: int
    text: str


@dataclass(slots=True)
class TelegramRouter:
    auth: TelegramOperatorAuth
    operator_service: TelegramOperatorService

    def handle_update(self, update: dict[str, object]) -> list[TelegramOutboundMessage]:
        message = update.get("message")
        if not isinstance(message, dict):
            return []
        chat = message.get("chat")
        text = message.get("text")
        if not isinstance(chat, dict) or not isinstance(text, str):
            return []
        chat_id = int(chat["id"])
        if not self.auth.is_allowed(chat_id):
            return [TelegramOutboundMessage(chat_id, formatter.unauthorized_message())]

        try:
            response = self._handle_command(text)
        except Exception as exc:
            response = formatter.command_error_message(exc)
        return [TelegramOutboundMessage(chat_id, response)]

    def _handle_command(self, text: str) -> str:
        parts = text.strip().split()
        command = parts[0].split("@", 1)[0].lower() if parts else ""
        if command in {"/start", "/help"}:
            return formatter.help_message()
        if command == "/status":
            return formatter.status_message(self.operator_service.get_status())
        if command == "/diagnostics":
            return formatter.diagnostics_message(self.operator_service.get_diagnostics())
        if command == "/scan":
            return formatter.scan_message(self.operator_service.get_scanner_results())
        if command == "/proposals":
            return formatter.proposals_message(self.operator_service.list_proposals())
        if command == "/proposal":
            if len(parts) < 2:
                raise ValueError("Usage: /proposal <id>")
            return formatter.proposal_message(self.operator_service.get_proposal_details(parts[1]))
        if command == "/alerts":
            return formatter.alerts_message(self.operator_service.list_alerts())
        return formatter.help_message()
