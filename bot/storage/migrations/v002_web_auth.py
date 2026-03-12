from __future__ import annotations


VERSION = 2
NAME = "web_auth"

SQL = """
CREATE TABLE IF NOT EXISTS web_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_user_active
ON web_sessions(user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS web_remember_tokens (
    remember_token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_web_remember_tokens_user_active
ON web_remember_tokens(user_id, expires_at DESC);
"""


def apply(connection) -> None:
    connection.executescript(SQL)
