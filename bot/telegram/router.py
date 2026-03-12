from __future__ import annotations

from dataclasses import dataclass

from bot.telegram import formatter
from bot.telegram.actions import parse_callback
from bot.telegram.auth import TelegramOperatorAuth
from bot.services.telegram_operator_service import TelegramOperatorService


@dataclass(slots=True)
class TelegramOutboundMessage:
    chat_id: int
    text: str
    reply_markup: dict[str, object] | None = None
    callback_query_id: str | None = None


@dataclass(slots=True)
class TelegramRouter:
    auth: TelegramOperatorAuth
    operator_service: TelegramOperatorService

    def handle_update(self, update: dict[str, object]) -> list[TelegramOutboundMessage]:
        callback_query = update.get("callback_query")
        if isinstance(callback_query, dict):
            return self._handle_callback_query(callback_query)
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
            response = self._handle_command(text, chat_id)
        except Exception as exc:
            response = TelegramOutboundMessage(chat_id, formatter.command_error_message(exc))
        return [response]

    def _handle_command(self, text: str, chat_id: int) -> TelegramOutboundMessage:
        parts = text.strip().split()
        command = parts[0].split("@", 1)[0].lower() if parts else ""
        if command in {"/start", "/help"}:
            return TelegramOutboundMessage(chat_id, formatter.help_message())
        if command == "/status":
            return TelegramOutboundMessage(chat_id, formatter.status_message(self.operator_service.get_status()))
        if command == "/diagnostics":
            return TelegramOutboundMessage(chat_id, formatter.diagnostics_message(self.operator_service.get_diagnostics()))
        if command == "/scan":
            return TelegramOutboundMessage(chat_id, formatter.scan_message(self.operator_service.get_scanner_results()))
        if command == "/proposals":
            return TelegramOutboundMessage(chat_id, formatter.proposals_message(self.operator_service.list_proposals()))
        if command == "/proposal":
            if len(parts) < 2:
                raise ValueError("Usage: /proposal <id>")
            proposal = self.operator_service.get_proposal_details(parts[1])
            return TelegramOutboundMessage(
                chat_id,
                formatter.proposal_message(proposal),
                reply_markup=formatter.proposal_actions_markup(proposal),
            )
        if command == "/approve":
            if len(parts) < 2:
                raise ValueError("Usage: /approve <id>")
            proposal = self.operator_service.approve_proposal(parts[1], chat_id)
            return TelegramOutboundMessage(chat_id, formatter.proposal_action_message("approve", proposal))
        if command == "/reject":
            if len(parts) < 2:
                raise ValueError("Usage: /reject <id>")
            proposal = self.operator_service.reject_proposal(parts[1], chat_id)
            return TelegramOutboundMessage(chat_id, formatter.proposal_action_message("reject", proposal))
        if command == "/cancel":
            if len(parts) < 2:
                raise ValueError("Usage: /cancel <id>")
            proposal = self.operator_service.cancel_proposal(parts[1], chat_id)
            return TelegramOutboundMessage(chat_id, formatter.proposal_action_message("cancel", proposal))
        if command == "/analysis":
            if len(parts) < 2:
                raise ValueError("Usage: /analysis <id>")
            return TelegramOutboundMessage(
                chat_id,
                formatter.proposal_analysis_message(self.operator_service.request_additional_analysis(parts[1], chat_id)),
            )
        if command == "/alerts":
            return TelegramOutboundMessage(chat_id, formatter.alerts_message(self.operator_service.list_alerts()))
        return TelegramOutboundMessage(chat_id, formatter.help_message())

    def _handle_callback_query(self, callback_query: dict[str, object]) -> list[TelegramOutboundMessage]:
        callback_id = callback_query.get("id")
        data = callback_query.get("data")
        message = callback_query.get("message")
        if not isinstance(callback_id, str) or not isinstance(data, str) or not isinstance(message, dict):
            return []
        chat = message.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            return []
        chat_id = int(chat["id"])
        if not self.auth.is_allowed(chat_id):
            return [TelegramOutboundMessage(chat_id, formatter.unauthorized_message(), callback_query_id=callback_id)]
        parsed = parse_callback(data)
        if parsed is None:
            return [TelegramOutboundMessage(chat_id, formatter.help_message(), callback_query_id=callback_id)]
        action, proposal_id = parsed
        try:
            if action == "details":
                proposal = self.operator_service.get_proposal_details(proposal_id)
                return [
                    TelegramOutboundMessage(
                        chat_id,
                        formatter.proposal_message(proposal),
                        reply_markup=formatter.proposal_actions_markup(proposal),
                        callback_query_id=callback_id,
                    )
                ]
            if action == "analysis":
                return [
                    TelegramOutboundMessage(
                        chat_id,
                        formatter.proposal_analysis_message(
                            self.operator_service.request_additional_analysis(proposal_id, chat_id)
                        ),
                        callback_query_id=callback_id,
                    )
                ]
            if action == "approve":
                proposal = self.operator_service.approve_proposal(proposal_id, chat_id)
            elif action == "reject":
                proposal = self.operator_service.reject_proposal(proposal_id, chat_id)
            elif action == "cancel":
                proposal = self.operator_service.cancel_proposal(proposal_id, chat_id)
            else:
                return [TelegramOutboundMessage(chat_id, formatter.help_message(), callback_query_id=callback_id)]
            return [
                TelegramOutboundMessage(
                    chat_id,
                    formatter.proposal_action_message(action, proposal),
                    callback_query_id=callback_id,
                )
            ]
        except Exception as exc:
            return [
                TelegramOutboundMessage(
                    chat_id,
                    formatter.command_error_message(exc),
                    callback_query_id=callback_id,
                )
            ]
