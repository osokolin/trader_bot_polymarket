from __future__ import annotations

import sqlite3
from pathlib import Path

from bot.storage.migrations import CURRENT_SCHEMA_VERSION, apply_migrations, current_schema_version


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            apply_migrations(connection)
        finally:
            connection.close()

    def schema_version(self) -> int:
        connection = self.connect()
        try:
            return current_schema_version(connection)
        finally:
            connection.close()

    @property
    def current_schema_version(self) -> int:
        return CURRENT_SCHEMA_VERSION
