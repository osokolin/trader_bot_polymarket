from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot.storage.db import Database
from bot.storage.migrations import CURRENT_SCHEMA_VERSION
from bot.storage.migrations.v001_initial import SQL as V001_SQL


class DatabaseMigrationsTest(unittest.TestCase):
    def _database(self) -> Database:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).exists() and Path(tmp.name).unlink())
        return Database(Path(tmp.name))

    def test_fresh_db_initialization_applies_current_schema_version(self) -> None:
        database = self._database()
        database.initialize()

        connection = database.connect()
        self.addCleanup(connection.close)
        version = connection.execute("SELECT version FROM schema_version").fetchone()["version"]
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        self.assertEqual(version, CURRENT_SCHEMA_VERSION)
        self.assertIn("trade_proposals", tables)
        self.assertIn("operator_action_requests", tables)
        self.assertIn("web_users", tables)
        self.assertIn("web_sessions", tables)
        self.assertIn("web_remember_tokens", tables)
        self.assertIn("execution_previews", tables)
        self.assertIn("schema_version", tables)

    def test_existing_baseline_schema_upgrades_to_versioned_schema(self) -> None:
        database = self._database()
        connection = database.connect()
        try:
            connection.executescript(V001_SQL)
            connection.commit()
        finally:
            connection.close()

        database.initialize()

        connection = database.connect()
        self.addCleanup(connection.close)
        version = connection.execute("SELECT version FROM schema_version").fetchone()["version"]
        self.assertEqual(version, CURRENT_SCHEMA_VERSION)

    def test_initialize_is_idempotent(self) -> None:
        database = self._database()
        database.initialize()
        database.initialize()

        connection = database.connect()
        self.addCleanup(connection.close)
        rows = connection.execute("SELECT version, applied_at FROM schema_version").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], CURRENT_SCHEMA_VERSION)

    def test_schema_version_access_works_after_startup(self) -> None:
        database = self._database()
        database.initialize()
        self.assertEqual(database.schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertEqual(database.current_schema_version, CURRENT_SCHEMA_VERSION)

    def test_startup_upgrade_preserves_existing_data(self) -> None:
        database = self._database()
        connection = database.connect()
        try:
            connection.executescript(V001_SQL)
            connection.execute(
                """
                INSERT INTO saved_views(view_id, name, kind, params_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("view_1", "test", "proposals_list", "{}", "2026-03-12T00:00:00+00:00"),
            )
            connection.commit()
        finally:
            connection.close()

        database.initialize()

        connection = database.connect()
        self.addCleanup(connection.close)
        row = connection.execute("SELECT name FROM saved_views WHERE view_id = ?", ("view_1",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "test")
