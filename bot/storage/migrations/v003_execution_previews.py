from __future__ import annotations


VERSION = 3
NAME = "execution_previews"

SQL = """
CREATE TABLE IF NOT EXISTS execution_previews (
    preview_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    event_id TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT NOT NULL,
    intended_price REAL NOT NULL,
    quoted_price REAL,
    intended_size_usd REAL NOT NULL,
    normalized_size_usd REAL,
    estimated_shares REAL,
    warnings_json TEXT NOT NULL,
    validation_errors_json TEXT NOT NULL,
    preview_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_previews_proposal_created
ON execution_previews(proposal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_execution_previews_status_created
ON execution_previews(status, created_at DESC);
"""


def apply(connection) -> None:
    connection.executescript(SQL)
