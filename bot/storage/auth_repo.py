from __future__ import annotations

import sqlite3
from datetime import datetime

from bot.domain.models import RememberBrowserToken, WebSession, WebUser


class WebAuthRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_user_by_username(self, username: str) -> WebUser | None:
        row = self.connection.execute(
            "SELECT * FROM web_users WHERE username = ?",
            (username,),
        ).fetchone()
        return None if row is None else self._row_to_user(row)

    def get_user(self, user_id: str) -> WebUser | None:
        row = self.connection.execute(
            "SELECT * FROM web_users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return None if row is None else self._row_to_user(row)

    def save_user(self, user: WebUser) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO web_users (
                user_id, username, password_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                user.user_id,
                user.username,
                user.password_hash,
                user.created_at.isoformat(),
                user.updated_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_session(self, session: WebSession) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO web_sessions (
                session_id, user_id, token_hash, csrf_token, created_at, expires_at, last_seen_at,
                user_agent, ip_address, revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.user_id,
                session.token_hash,
                session.csrf_token,
                session.created_at.isoformat(),
                session.expires_at.isoformat(),
                session.last_seen_at.isoformat(),
                session.user_agent,
                session.ip_address,
                None if session.revoked_at is None else session.revoked_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_session(self, session_id: str) -> WebSession | None:
        row = self.connection.execute(
            "SELECT * FROM web_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return None if row is None else self._row_to_session(row)

    def revoke_session(self, session_id: str, revoked_at: datetime) -> None:
        self.connection.execute(
            "UPDATE web_sessions SET revoked_at = ? WHERE session_id = ?",
            (revoked_at.isoformat(), session_id),
        )
        self.connection.commit()

    def revoke_all_sessions_for_user(self, user_id: str, revoked_at: datetime) -> None:
        self.connection.execute(
            "UPDATE web_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (revoked_at.isoformat(), user_id),
        )
        self.connection.commit()

    def save_remember_token(self, token: RememberBrowserToken) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO web_remember_tokens (
                remember_token_id, user_id, token_hash, created_at, expires_at, last_used_at,
                user_agent, ip_address, revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token.remember_token_id,
                token.user_id,
                token.token_hash,
                token.created_at.isoformat(),
                token.expires_at.isoformat(),
                token.last_used_at.isoformat(),
                token.user_agent,
                token.ip_address,
                None if token.revoked_at is None else token.revoked_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_remember_token(self, remember_token_id: str) -> RememberBrowserToken | None:
        row = self.connection.execute(
            "SELECT * FROM web_remember_tokens WHERE remember_token_id = ?",
            (remember_token_id,),
        ).fetchone()
        return None if row is None else self._row_to_remember_token(row)

    def revoke_remember_token(self, remember_token_id: str, revoked_at: datetime) -> None:
        self.connection.execute(
            "UPDATE web_remember_tokens SET revoked_at = ? WHERE remember_token_id = ?",
            (revoked_at.isoformat(), remember_token_id),
        )
        self.connection.commit()

    def revoke_all_remember_tokens_for_user(self, user_id: str, revoked_at: datetime) -> None:
        self.connection.execute(
            """
            UPDATE web_remember_tokens
            SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (revoked_at.isoformat(), user_id),
        )
        self.connection.commit()

    def count_active_sessions(self, user_id: str, now: datetime) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM web_sessions
            WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (user_id, now.isoformat()),
        ).fetchone()
        return 0 if row is None else int(row["count"])

    def count_active_remember_tokens(self, user_id: str, now: datetime) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM web_remember_tokens
            WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (user_id, now.isoformat()),
        ).fetchone()
        return 0 if row is None else int(row["count"])

    def _row_to_user(self, row: sqlite3.Row) -> WebUser:
        return WebUser(
            user_id=row["user_id"],
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_session(self, row: sqlite3.Row) -> WebSession:
        return WebSession(
            session_id=row["session_id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            csrf_token=row["csrf_token"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            user_agent=row["user_agent"],
            ip_address=row["ip_address"],
            revoked_at=None if row["revoked_at"] is None else datetime.fromisoformat(row["revoked_at"]),
        )

    def _row_to_remember_token(self, row: sqlite3.Row) -> RememberBrowserToken:
        return RememberBrowserToken(
            remember_token_id=row["remember_token_id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            last_used_at=datetime.fromisoformat(row["last_used_at"]),
            user_agent=row["user_agent"],
            ip_address=row["ip_address"],
            revoked_at=None if row["revoked_at"] is None else datetime.fromisoformat(row["revoked_at"]),
        )
