from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, UTC

from bot.storage.migrations import v001_initial, v002_web_auth, v003_execution_previews


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationStep:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(version=v001_initial.VERSION, name=v001_initial.NAME, apply=v001_initial.apply),
    MigrationStep(version=v002_web_auth.VERSION, name=v002_web_auth.NAME, apply=v002_web_auth.apply),
    MigrationStep(
        version=v003_execution_previews.VERSION,
        name=v003_execution_previews.NAME,
        apply=v003_execution_previews.apply,
    ),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def ensure_schema_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = connection.execute("SELECT COUNT(*) AS count FROM schema_version").fetchone()
    if row is not None and row["count"] == 0:
        connection.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
            (0, _now_iso()),
        )
    connection.commit()


def current_schema_version(connection: sqlite3.Connection) -> int:
    ensure_schema_version_table(connection)
    row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    return 0 if row is None else int(row["version"])


def apply_migrations(connection: sqlite3.Connection) -> int:
    ensure_schema_version_table(connection)
    version = current_schema_version(connection)
    for migration in MIGRATIONS:
        if migration.version <= version:
            continue
        try:
            migration.apply(connection)
            connection.execute(
                "UPDATE schema_version SET version = ?, applied_at = ?",
                (migration.version, _now_iso()),
            )
            connection.commit()
            version = migration.version
        except Exception as exc:
            connection.rollback()
            raise MigrationError(f"Failed to apply migration v{migration.version:03d}_{migration.name}") from exc
    return version


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
