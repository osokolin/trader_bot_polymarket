from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from bot.adapters.polymarket.clob_client import ClobMarketDataClient
from bot.adapters.polymarket.errors import PolymarketAdapterError
from bot.adapters.polymarket.gamma_client import GammaApiClient
from bot.adapters.polymarket.websocket_market import PublicMarketWebSocketClient


@dataclass(slots=True)
class DiagnosticCheckResult:
    ok: bool
    message: str


@dataclass(slots=True)
class PolymarketDiagnosticsResult:
    gamma: DiagnosticCheckResult
    clob_rest: DiagnosticCheckResult
    websocket: DiagnosticCheckResult
    database: DiagnosticCheckResult
    overall_ok: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "gamma": asdict(self.gamma),
            "clob_rest": asdict(self.clob_rest),
            "websocket": asdict(self.websocket),
            "database": asdict(self.database),
            "overall_ok": self.overall_ok,
        }


class PolymarketDiagnosticsService:
    def __init__(
        self,
        gamma_client: GammaApiClient,
        clob_client: ClobMarketDataClient,
        websocket_client: PublicMarketWebSocketClient,
        database_url: str | None = None,
    ) -> None:
        self.gamma_client = gamma_client
        self.clob_client = clob_client
        self.websocket_client = websocket_client
        self.database_url = database_url if database_url is not None else os.getenv("BOT_DATABASE_URL")

    def run(self) -> PolymarketDiagnosticsResult:
        gamma = self._safe_check(self._check_gamma)
        clob_rest = self._safe_check(self._check_clob_rest)
        websocket = self._safe_check(self._check_websocket)
        database = self._safe_check(self._check_database)
        return PolymarketDiagnosticsResult(
            gamma=gamma,
            clob_rest=clob_rest,
            websocket=websocket,
            database=database,
            overall_ok=all(item.ok for item in [gamma, clob_rest, websocket, database]),
        )

    def _safe_check(self, check: Callable[[], DiagnosticCheckResult]) -> DiagnosticCheckResult:
        try:
            return check()
        except PolymarketAdapterError as exc:
            return DiagnosticCheckResult(False, str(exc))
        except (sqlite3.Error, OSError, ValueError) as exc:
            return DiagnosticCheckResult(False, str(exc))
        except Exception as exc:  # pragma: no cover - defensive guard for CLI safety
            return DiagnosticCheckResult(False, f"Unexpected diagnostics failure ({type(exc).__name__})")

    def _check_gamma(self) -> DiagnosticCheckResult:
        result = self.gamma_client.probe()
        return DiagnosticCheckResult(True, f"reachable ({result.get('status', 'ok')})")

    def _check_clob_rest(self) -> DiagnosticCheckResult:
        result = self.clob_client.probe()
        return DiagnosticCheckResult(True, f"reachable (HTTP {result.get('status_code', '?')})")

    def _check_websocket(self) -> DiagnosticCheckResult:
        result = asyncio.run(self.websocket_client.smoke_check())
        return DiagnosticCheckResult(True, f"reachable ({result.get('update_count', 0)} updates)")

    def _check_database(self) -> DiagnosticCheckResult:
        if not self.database_url:
            raise ValueError("BOT_DATABASE_URL is not set")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("BOT_DATABASE_URL must use sqlite:///...")
        path = Path(self.database_url.removeprefix("sqlite:///"))
        parent = path.parent if str(path.parent) else Path(".")
        if not parent.exists():
            raise ValueError(f"Database directory does not exist: {parent}")
        if not os.access(parent, os.W_OK):
            raise ValueError(f"Database directory is not writable: {parent}")
        if not path.exists():
            raise ValueError(f"Database file does not exist: {path}")
        if not os.access(path, os.W_OK):
            raise ValueError(f"Database file is not writable: {path}")
        connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
        try:
            connection.execute("SELECT 1")
        finally:
            connection.close()
        return DiagnosticCheckResult(True, f"sqlite ready ({path})")
