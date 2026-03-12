from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from bot.telegram import formatter
from bot.telegram.router import TelegramRouter
from bot.services.telegram_operator_service import TelegramOperatorService


@dataclass(slots=True)
class TelegramApiClient:
    token: str
    timeout_seconds: float = 30.0
    http_client: httpx.Client = field(default_factory=httpx.Client)

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, object]]:
        payload: dict[str, object] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        response = self.http_client.get(f"{self.base_url}/getUpdates", params=payload, timeout=self.timeout_seconds + timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError("Telegram getUpdates failed")
        return data.get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        self.send_message_with_markup(chat_id, text, reply_markup=None)

    def send_message_with_markup(self, chat_id: int, text: str, reply_markup: dict[str, object] | None) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.http_client.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError("Telegram sendMessage failed")

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, object] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:160]
        response = self.http_client.post(
            f"{self.base_url}/answerCallbackQuery",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError("Telegram answerCallbackQuery failed")

    def close(self) -> None:
        self.http_client.close()


@dataclass(slots=True)
class TelegramBotApp:
    client: TelegramApiClient
    router: TelegramRouter
    operator_service: TelegramOperatorService
    poll_timeout_seconds: int = 30

    def serve_forever(self) -> None:
        offset: int | None = None
        while True:
            offset = self.run_cycle(offset)

    def run_cycle(self, offset: int | None = None) -> int | None:
        updates = self.client.get_updates(offset=offset, timeout=self.poll_timeout_seconds)
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = update_id + 1
            for outbound in self.router.handle_update(update):
                if outbound.callback_query_id is not None:
                    self.client.answer_callback_query(outbound.callback_query_id, text=outbound.text.splitlines()[0])
                self.client.send_message_with_markup(outbound.chat_id, outbound.text, outbound.reply_markup)
        for notification in self.operator_service.poll_notifications():
            text = formatter.notification_message(notification)
            reply_markup = formatter.notification_markup(notification)
            for chat_id in sorted(self.router.auth.allowed_chat_ids):
                self.client.send_message_with_markup(chat_id, text, reply_markup)
        return next_offset


def build_telegram_bot_app(router: TelegramRouter, operator_service: TelegramOperatorService) -> TelegramBotApp:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")
    return TelegramBotApp(
        client=TelegramApiClient(token=token),
        router=router,
        operator_service=operator_service,
    )
