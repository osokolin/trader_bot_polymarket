from __future__ import annotations


VERSION = 1
NAME = "initial"

SQL = """
CREATE TABLE IF NOT EXISTS trade_proposals (
    proposal_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    market_category TEXT NOT NULL,
    status TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT NOT NULL,
    market_price REAL NOT NULL,
    fair_probability REAL NOT NULL,
    edge REAL NOT NULL,
    confidence REAL NOT NULL,
    model_agreement INTEGER NOT NULL,
    trusted_source_present INTEGER NOT NULL,
    source_types_json TEXT NOT NULL,
    current_size_usd REAL NOT NULL,
    current_limit_price REAL NOT NULL,
    recommended_size_usd REAL NOT NULL,
    max_allowed_size_usd REAL NOT NULL,
    suggested_limit_price REAL NOT NULL,
    thesis_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    policy_allowed INTEGER NOT NULL,
    policy_reasons_json TEXT NOT NULL,
    policy_details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposal_reviews (
    review_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intent_reviews (
    review_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_intents (
    intent_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    side TEXT NOT NULL,
    size_usd REAL NOT NULL,
    limit_price REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    superseded_by_intent_id TEXT
);

CREATE TABLE IF NOT EXISTS simulated_executions (
    execution_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    status TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    order_id TEXT,
    reference_price REAL NOT NULL,
    best_bid REAL,
    best_ask REAL,
    simulated_price REAL,
    slippage_bps REAL,
    filled_size_usd REAL NOT NULL,
    fill_timestamp TEXT,
    latency_ms INTEGER,
    completion_reason TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulated_fill_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    fragment_index INTEGER NOT NULL,
    price REAL NOT NULL,
    size_usd REAL NOT NULL,
    remaining_size_usd REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    event_timestamp TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_entries (
    watch_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_target
ON watchlist_entries(target_type, target_id);

CREATE TABLE IF NOT EXISTS operator_alerts (
    alert_id TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    related_market_id TEXT,
    related_proposal_id TEXT,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT,
    dismissed_at TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS operator_action_requests (
    request_id TEXT PRIMARY KEY,
    request_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    actioned_at TEXT,
    actioned_by TEXT,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operator_action_requests_status_updated
ON operator_action_requests(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS operator_action_request_records (
    record_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    result TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probability_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    proposal_id TEXT,
    fair_probability REAL NOT NULL,
    confidence REAL NOT NULL,
    model_agreement INTEGER NOT NULL,
    trusted_source_present INTEGER NOT NULL,
    source_types_json TEXT NOT NULL,
    key_factors_json TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    confidence_components_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    source_inputs_json TEXT NOT NULL,
    evidence_records_json TEXT NOT NULL,
    source_type_contributions_json TEXT NOT NULL,
    research_summary TEXT NOT NULL,
    research_key_factors_json TEXT NOT NULL,
    thesis_points_json TEXT NOT NULL,
    risk_points_json TEXT NOT NULL,
    evidence_summary_json TEXT NOT NULL,
    current_price REAL NOT NULL,
    data_age_seconds INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_data_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    source TEXT NOT NULL,
    market_payload_json TEXT NOT NULL,
    orderbook_payload_json TEXT NOT NULL,
    websocket_payload_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    stale INTEGER NOT NULL,
    reference_price REAL,
    pricing_metadata_json TEXT NOT NULL,
    data_age_seconds INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_data_snapshots_market_fetched
ON market_data_snapshots(market_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS decision_reviews (
    review_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    market_id TEXT NOT NULL,
    proposal_id TEXT,
    probability_snapshot_id TEXT,
    previous_snapshot_id TEXT,
    intent_id TEXT,
    execution_id TEXT,
    confidence_outcome TEXT NOT NULL,
    probability_outcome TEXT NOT NULL,
    execution_outcome TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    proposal_id TEXT,
    intent_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcome_analysis_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    group_by TEXT NOT NULL,
    since_hours INTEGER,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_views (
    view_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    size_usd REAL NOT NULL,
    entry_price REAL NOT NULL,
    status TEXT NOT NULL,
    theme TEXT,
    opened_at TEXT NOT NULL
);
"""


def apply(connection) -> None:
    connection.executescript(SQL)
