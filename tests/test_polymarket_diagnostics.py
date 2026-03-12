from __future__ import annotations

import io
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bot.adapters.polymarket.errors import PolymarketHTTPError, PolymarketTransportError, PolymarketWebSocketError
from bot.cli.app import main
from bot.services.polymarket_diagnostics import (
    DiagnosticCheckResult,
    PolymarketDiagnosticsResult,
    PolymarketDiagnosticsService,
)


class _HealthyGammaClient:
    def probe(self) -> dict[str, object]:
        return {"status": "ok", "items": 1}


class _HealthyClobClient:
    def probe(self) -> dict[str, object]:
        return {"status": "ok", "status_code": 200}


class _HealthyWebSocketClient:
    async def smoke_check(self, asset_ids: list[str] | None = None) -> dict[str, object]:
        return {"status": "ok", "update_count": 1}


class PolymarketDiagnosticsTest(unittest.TestCase):
    def test_healthy_diagnostics_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "diag.db"
            sqlite3.connect(db_path).close()
            service = PolymarketDiagnosticsService(
                gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
                clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
                websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
                database_url=f"sqlite:///{db_path}",
            )
            result = service.run()
            self.assertTrue(result.gamma.ok)
            self.assertTrue(result.clob_rest.ok)
            self.assertTrue(result.websocket.ok)
            self.assertTrue(result.database.ok)
            self.assertTrue(result.overall_ok)

    def test_gamma_failure(self) -> None:
        class FailingGammaClient:
            def probe(self) -> dict[str, object]:
                raise PolymarketTransportError("Gamma unreachable")

        service = PolymarketDiagnosticsService(
            gamma_client=FailingGammaClient(),  # type: ignore[arg-type]
            clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
            websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
            database_url="sqlite:///missing.db",
        )
        result = service.run()
        self.assertFalse(result.gamma.ok)
        self.assertEqual(result.gamma.message, "Gamma unreachable")

    def test_clob_rest_failure(self) -> None:
        class FailingClobClient:
            def probe(self) -> dict[str, object]:
                raise PolymarketHTTPError("CLOB returned 503")

        service = PolymarketDiagnosticsService(
            gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
            clob_client=FailingClobClient(),  # type: ignore[arg-type]
            websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
            database_url="sqlite:///missing.db",
        )
        result = service.run()
        self.assertFalse(result.clob_rest.ok)
        self.assertEqual(result.clob_rest.message, "CLOB returned 503")

    def test_websocket_timeout_failure(self) -> None:
        class FailingWebSocketClient:
            async def smoke_check(self, asset_ids: list[str] | None = None) -> dict[str, object]:
                raise PolymarketWebSocketError("Market WebSocket smoke check timed out")

        service = PolymarketDiagnosticsService(
            gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
            clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
            websocket_client=FailingWebSocketClient(),  # type: ignore[arg-type]
            database_url="sqlite:///missing.db",
        )
        result = service.run()
        self.assertFalse(result.websocket.ok)
        self.assertEqual(result.websocket.message, "Market WebSocket smoke check timed out")

    def test_database_config_missing(self) -> None:
        service = PolymarketDiagnosticsService(
            gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
            clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
            websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
            database_url=None,
        )
        result = service.run()
        self.assertFalse(result.database.ok)
        self.assertEqual(result.database.message, "BOT_DATABASE_URL is not set")

    def test_database_config_invalid_scheme(self) -> None:
        invalid = PolymarketDiagnosticsService(
            gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
            clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
            websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
            database_url="postgres://not-supported",
        )
        result = invalid.run()
        self.assertFalse(result.database.ok)
        self.assertEqual(result.database.message, "BOT_DATABASE_URL must use sqlite:///...")

    def test_database_config_unwritable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir) / "locked"
            directory.mkdir()
            os.chmod(directory, stat.S_IREAD | stat.S_IEXEC)
            try:
                unwritable = PolymarketDiagnosticsService(
                    gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
                    clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
                    websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
                    database_url=f"sqlite:///{directory / 'diag.db'}",
                )
                result = unwritable.run()
                self.assertFalse(result.database.ok)
            finally:
                os.chmod(directory, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

    def test_database_config_missing_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "missing.db"
            service = PolymarketDiagnosticsService(
                gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
                clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
                websocket_client=_HealthyWebSocketClient(),  # type: ignore[arg-type]
                database_url=f"sqlite:///{db_path}",
            )
            result = service.run()
            self.assertFalse(result.database.ok)
            self.assertEqual(result.database.message, f"Database file does not exist: {db_path}")

    def test_structured_error_output_hides_raw_exceptions(self) -> None:
        class ExplodingWebSocketClient:
            async def smoke_check(self, asset_ids: list[str] | None = None) -> dict[str, object]:
                raise RuntimeError("boom: internal details")

        service = PolymarketDiagnosticsService(
            gamma_client=_HealthyGammaClient(),  # type: ignore[arg-type]
            clob_client=_HealthyClobClient(),  # type: ignore[arg-type]
            websocket_client=ExplodingWebSocketClient(),  # type: ignore[arg-type]
            database_url="sqlite:///missing.db",
        )
        result = service.run()
        self.assertFalse(result.websocket.ok)
        self.assertEqual(result.websocket.message, "Unexpected diagnostics failure (RuntimeError)")

    def test_cli_polymarket_diagnostics_output_is_operator_readable(self) -> None:
        fake_result = PolymarketDiagnosticsResult(
            gamma=DiagnosticCheckResult(True, "reachable"),
            clob_rest=DiagnosticCheckResult(True, "reachable"),
            websocket=DiagnosticCheckResult(False, "timeout"),
            database=DiagnosticCheckResult(True, "sqlite ready"),
            overall_ok=False,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path("config").resolve()
            db_path = Path(tmp_dir) / "diag.db"
            env = {"BOT_DATABASE_URL": f"sqlite:///{db_path}"}
            with patch.dict(os.environ, env, clear=False), patch(
                "bot.cli.app.PolymarketDiagnosticsService"
            ) as diagnostics_cls:
                diagnostics_cls.return_value.run.return_value = fake_result
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(["--config-dir", str(config_dir), "diagnostics", "polymarket"])
                output = buffer.getvalue()
                self.assertEqual(exit_code, 0)
                self.assertIn("Polymarket diagnostics", output)
                self.assertIn("Gamma API", output)
                self.assertIn("CLOB REST", output)
                self.assertIn("WebSocket", output)
                self.assertIn("Database", output)
                self.assertIn("Overall status ..... FAIL", output)
                self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
