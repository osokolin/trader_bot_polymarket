from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from bot.adapters.polymarket.errors import PolymarketParseError, PolymarketTransportError, PolymarketWebSocketError
from bot.adapters.polymarket.models import ClobMarketUpdate


WebSocketConnector = Callable[[str], Awaitable[Any]]
SleepFunc = Callable[[float], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class PublicMarketWebSocketClient:
    websocket_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    max_reconnect_attempts: int = 3
    base_backoff_seconds: float = 0.25
    recv_timeout_seconds: float = 5.0
    connector: WebSocketConnector | None = None
    sleep_func: SleepFunc = asyncio.sleep

    async def stream_market(self, asset_ids: list[str], max_messages: int = 1) -> list[ClobMarketUpdate]:
        if not asset_ids:
            raise PolymarketWebSocketError("At least one asset_id is required for the market stream")
        connector = self._resolve_connector()
        attempts = 0
        while True:
            try:
                connection = connector(self.websocket_url)
                if inspect.isawaitable(connection):
                    connection = await connection
                async with connection as websocket:
                    await websocket.send(json.dumps({"asset_ids": asset_ids, "type": "market"}))
                    updates: list[ClobMarketUpdate] = []
                    while len(updates) < max_messages:
                        try:
                            raw_message = await asyncio.wait_for(websocket.recv(), timeout=self.recv_timeout_seconds)
                        except asyncio.TimeoutError as exc:
                            raise PolymarketWebSocketError("Market WebSocket receive timeout") from exc
                        updates.extend(self._parse_message(raw_message))
                        if len(updates) >= max_messages:
                            return updates[:max_messages]
            except ModuleNotFoundError as exc:
                raise PolymarketWebSocketError("websockets package is required for market WebSocket streaming") from exc
            except PolymarketParseError:
                raise
            except PolymarketWebSocketError as exc:
                attempts += 1
                if attempts >= self.max_reconnect_attempts:
                    raise PolymarketTransportError("WebSocket market stream timed out after reconnect attempts") from exc
                await self.sleep_func(self.base_backoff_seconds * (2 ** (attempts - 1)))
            except Exception as exc:  # pragma: no cover
                attempts += 1
                if attempts >= self.max_reconnect_attempts:
                    raise PolymarketTransportError("WebSocket market stream unavailable after reconnect attempts") from exc
                await self.sleep_func(self.base_backoff_seconds * (2 ** (attempts - 1)))

    def _resolve_connector(self) -> WebSocketConnector:
        if self.connector is not None:
            return self.connector
        websockets = importlib.import_module("websockets")
        return websockets.connect

    def _parse_message(self, raw_message: Any) -> list[ClobMarketUpdate]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        if isinstance(raw_message, str):
            try:
                payload = json.loads(raw_message)
            except ValueError as exc:
                raise PolymarketParseError("Invalid JSON frame from market WebSocket") from exc
        else:
            payload = raw_message
        if isinstance(payload, dict):
            payloads = [payload]
        elif isinstance(payload, list):
            payloads = payload
        else:
            raise PolymarketParseError("Unexpected market WebSocket payload shape")
        updates: list[ClobMarketUpdate] = []
        for item in payloads:
            if not isinstance(item, dict):
                raise PolymarketParseError("Unexpected market WebSocket item shape")
            try:
                best_bid = float(item.get("best_bid") or item.get("bestBid") or item.get("bid"))
                best_ask = float(item.get("best_ask") or item.get("bestAsk") or item.get("ask"))
                midpoint = round((best_bid + best_ask) / 2, 4)
                spread_pct = 0.0 if midpoint == 0 else round((best_ask - best_bid) / midpoint, 6)
                asset_id = item.get("asset_id") or item.get("assetId") or item.get("token_id")
                if asset_id is None:
                    raise PolymarketParseError("Market WebSocket payload missing asset_id")
                updates.append(
                    ClobMarketUpdate(
                        asset_id=str(asset_id),
                        market_id=None if item.get("market") is None else str(item.get("market")),
                        best_bid=best_bid,
                        best_ask=best_ask,
                        midpoint=midpoint,
                        spread_pct=spread_pct,
                        timestamp=_parse_datetime(item.get("timestamp") or item.get("ts")),
                        reference_price=None if item.get("price") is None else float(item["price"]),
                        sequence_id=None if item.get("hash") is None else str(item["hash"]),
                        raw_payload=item,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PolymarketParseError("Malformed market WebSocket payload") from exc
        return updates
