from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.domain.decisions import PolicyDecision
from bot.domain.enums import (
    AlertState,
    AlertSeverity,
    AlertType,
    IntentStatus,
    PositionStatus,
    ProposalStatus,
    SourceType,
    TradeAction,
    WatchTargetType,
)


@dataclass(slots=True)
class Market:
    market_id: str
    title: str
    category: str
    liquidity_usd: float
    spread_pct: float
    resolution_time: datetime
    rules_text: str
    rules_confidence: float
    tags: list[str] = field(default_factory=list)
    has_orderbook: bool = True


@dataclass(slots=True)
class OrderBookSnapshot:
    market_id: str
    best_bid: float
    best_ask: float
    midpoint: float
    spread_pct: float
    timestamp: datetime


@dataclass(slots=True)
class Signal:
    signal_id: str
    market_id: str
    source_type: SourceType
    source_name: str
    confidence: float
    relevance_score: float
    supports_trade: bool
    thesis_point: str
    risk_point: str


@dataclass(slots=True)
class ProbabilityEstimate:
    market_id: str
    fair_probability: float
    confidence: float
    model_agreement: int
    trusted_source_present: bool
    source_types: list[SourceType]
    key_factors: list[str] = field(default_factory=list)
    source_count: int = 0
    confidence_components: dict[str, float] = field(default_factory=dict)
    explanation: str = ""
    source_inputs: list[dict[str, object]] = field(default_factory=list)
    evidence_records: list["EvidenceRecord"] = field(default_factory=list)
    source_type_contributions: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceRecord:
    source_id: str
    source_name: str
    source_type: SourceType
    weight: float
    contribution: float
    summary: str
    supports_trade: bool = True


@dataclass(slots=True)
class TradeProposal:
    proposal_id: str
    market_id: str
    market_title: str
    market_category: str
    action: TradeAction
    side: str
    market_price: float
    fair_probability: float
    edge: float
    confidence: float
    model_agreement: int
    trusted_source_present: bool
    source_types: list[SourceType]
    current_size_usd: float
    current_limit_price: float
    recommended_size_usd: float
    max_allowed_size_usd: float
    suggested_limit_price: float
    thesis: list[str]
    risks: list[str]
    status: ProposalStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    policy_decision: PolicyDecision


@dataclass(slots=True)
class Position:
    position_id: str
    market_id: str
    size_usd: float
    entry_price: float
    status: PositionStatus
    opened_at: datetime
    theme: str | None = None


@dataclass(slots=True)
class ExitProposal:
    proposal_id: str
    position_id: str
    market_id: str
    reason: str
    status: ProposalStatus
    created_at: datetime


@dataclass(slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    entity_id: str
    message: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class OrderIntent:
    intent_id: str
    proposal_id: str
    market_id: str
    side: str
    size_usd: float
    limit_price: float
    status: IntentStatus
    created_at: datetime
    updated_at: datetime
    reason: str
    superseded_by_intent_id: str | None = None


@dataclass(slots=True)
class SimulatedExecution:
    execution_id: str
    intent_id: str
    status: IntentStatus
    accepted: bool
    order_id: str | None
    reference_price: float
    best_bid: float | None
    best_ask: float | None
    simulated_price: float | None
    slippage_bps: float | None
    filled_size_usd: float
    fill_timestamp: datetime | None
    latency_ms: int | None
    completion_reason: str | None
    message: str
    created_at: datetime


@dataclass(slots=True)
class SimulatedFillEvent:
    event_id: str
    execution_id: str
    intent_id: str
    event_type: str
    fragment_index: int
    price: float
    size_usd: float
    remaining_size_usd: float
    latency_ms: int
    event_timestamp: datetime
    message: str


@dataclass(slots=True)
class ExecutionEvaluation:
    evaluation_id: str
    proposal_id: str | None
    intent_id: str
    execution_id: str
    verdict: str
    intended_price: float
    realized_price: float | None
    expected_size_usd: float
    filled_size_usd: float
    expected_latency_ms: int
    realized_latency_ms: int | None
    intended_completion: str
    actual_completion_reason: str
    size_fill_ratio: float
    price_delta: float | None
    latency_delta_ms: int | None
    timeline_event_count: int
    summary: str
    created_at: datetime


@dataclass(slots=True)
class ExecutionEvaluationSnapshot:
    evaluation_id: str
    proposal_id: str | None
    intent_id: str
    execution_id: str
    verdict: str
    summary: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class OutcomeAnalysisGroup:
    group_by: str
    group_value: str
    review_count: int
    evaluation_count: int
    average_fair_probability_delta: float | None
    average_confidence_delta: float | None
    confidence_held_count: int
    confidence_degraded_count: int
    probability_in_favor_count: int
    probability_against_count: int
    execution_favorable_count: int
    execution_unfavorable_count: int
    verdict_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class OutcomeAnalysisSnapshot:
    snapshot_id: str
    scope: str
    group_by: str
    since_hours: int | None
    groups: list[OutcomeAnalysisGroup]
    summary: str
    created_at: datetime


@dataclass(slots=True)
class SimulationSummary:
    scope: str
    execution_count: int
    accepted_count: int
    filled_count: int
    partial_fill_count: int
    resting_count: int
    rejected_count: int
    total_filled_size_usd: float
    average_slippage_bps: float | None
    latest_fill_timestamp: datetime | None


@dataclass(slots=True)
class AnalyticsSummary:
    scope: str
    since_hours: int | None
    active_proposal_count: int
    approved_proposal_count: int
    active_intent_count: int
    terminal_intent_count: int
    simulated_execution_count: int
    total_simulated_filled_size_usd: float
    average_simulated_slippage_bps: float | None


@dataclass(slots=True)
class ResearchSummary:
    market_id: str
    proposal_id: str | None
    summary: str
    key_factors: list[str] = field(default_factory=list)
    thesis_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    source_count: int = 0
    evidence_summary: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProbabilitySnapshot:
    snapshot_id: str
    market_id: str
    proposal_id: str | None
    probability: ProbabilityEstimate
    research_summary: ResearchSummary
    current_price: float
    data_age_seconds: int
    created_at: datetime


@dataclass(slots=True)
class ProbabilityDrift:
    scope: str
    latest_snapshot: ProbabilitySnapshot
    previous_snapshot: ProbabilitySnapshot | None
    fair_probability_delta: float | None
    confidence_delta: float | None
    source_count_delta: int | None
    confidence_component_deltas: dict[str, float]
    source_type_contribution_deltas: dict[str, float]
    added_key_factors: list[str] = field(default_factory=list)
    removed_key_factors: list[str] = field(default_factory=list)
    added_evidence_sources: list[str] = field(default_factory=list)
    removed_evidence_sources: list[str] = field(default_factory=list)
    drift_summary: str = ""


@dataclass(slots=True)
class DecisionReview:
    review_id: str
    scope: str
    market_id: str
    proposal: TradeProposal | None
    probability_snapshot: ProbabilitySnapshot | None
    probability_drift: ProbabilityDrift | None
    latest_intent: OrderIntent | None
    latest_execution: SimulatedExecution | None
    confidence_outcome: str
    probability_outcome: str
    execution_outcome: str
    summary: str
    created_at: datetime


@dataclass(slots=True)
class DecisionReviewSnapshot:
    review_id: str
    scope: str
    market_id: str
    proposal_id: str | None
    probability_snapshot_id: str | None
    previous_snapshot_id: str | None
    intent_id: str | None
    execution_id: str | None
    confidence_outcome: str
    probability_outcome: str
    execution_outcome: str
    summary: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class WatchlistEntry:
    watch_id: str
    target_type: WatchTargetType
    target_id: str
    label: str | None
    created_at: datetime


@dataclass(slots=True)
class OperatorAlert:
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    state: AlertState
    entity_type: WatchTargetType
    entity_id: str
    related_market_id: str | None
    related_proposal_id: str | None
    summary: str
    payload: dict[str, object]
    created_at: datetime
    acknowledged_at: datetime | None = None
    dismissed_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass(slots=True)
class SavedView:
    view_id: str
    name: str
    kind: str
    params: dict[str, object]
    created_at: datetime
